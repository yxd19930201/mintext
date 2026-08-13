"""
AI Service — real httpx implementation for OpenAI-compatible APIs.
Falls back to settings (env vars) when no explicit config is provided.
"""
from __future__ import annotations

import json
import hashlib
import logging
import re
import asyncio
from types import SimpleNamespace
import httpx
from fastapi import HTTPException, status
from app.config import settings
from app.models.ai_config import AIConfig
from app.services.creative_prompt_service import creative_prompt, normalize_short_script
from app.services.novel_skill_service import novel_skill_prompt
from app.services.ai_usage_service import ai_usage_service

logger = logging.getLogger(__name__)


def normalize_chapter_paragraphs(content: str) -> str:
    """Preserve authored paragraphs and repair long prose flattened to one line."""
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return text

    # Existing paragraph structure is authoritative; only tidy excessive gaps.
    if "\n" in text:
        lines = [line.strip() for line in text.split("\n")]
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            if line:
                current.append(line)
            elif current:
                paragraphs.append("\n".join(current))
                current = []
        if current:
            paragraphs.append("\n".join(current))
        return "\n\n".join(paragraphs)

    # Short strings are usually titles, summaries, or dialogue snippets rather
    # than full chapter prose and should not be reformatted.
    if len(text) < 500:
        return text

    sentences = [
        match.group(0).strip()
        for match in re.finditer(r".*?(?:[。！？!?]+[”’」』\"]*|$)", text)
        if match.group(0).strip()
    ]
    if len(sentences) < 4:
        return text

    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        starts_dialogue = sentence.startswith(("“", '"'))
        if current and starts_dialogue and len(current) >= 90:
            paragraphs.append(current.strip())
            current = ""
        current += sentence
        ends_dialogue = sentence.endswith(("”", '"'))
        if len(current) >= 220 or (ends_dialogue and len(current) >= 100):
            paragraphs.append(current.strip())
            current = ""
    if current.strip():
        paragraphs.append(current.strip())

    return "\n\n".join(paragraphs) if len(paragraphs) > 1 else text


def _audit_focus_rules(payload: dict) -> str:
    """Select only the semantic audit modules relevant to this chapter."""
    # Historical ledger entries can mention every subject the novel has ever
    # covered. Module routing must use only the current chapter surface, or a
    # past stock arc would keep loading securities rules during later factory,
    # property or relationship chapters.
    current_surface = {
        "chapter_outline": payload.get("chapter_outline") or {},
        "previous_ending": payload.get("previous_ending") or "",
        "candidate_content": payload.get("candidate_content") or "",
    }
    text = json.dumps(current_surface, ensure_ascii=False)
    rules = [
        "【通用连续性】核对上一章结尾、本章大纲、路线图、时间地点、人物关系、称呼、语言、"
        "知识边界、物品归属和下一章入口；对白的说话人、回答人和动作执行人必须一致。",
        "【通用事件状态机】所有事件按“意向/待办→条件确认→执行→结果凭证→状态入账”推进；"
        "后一步必须有前一步证据。签约不等于履行，承诺不等于付款，申请不等于获批，"
        "发货不等于验收，未实际发生的动作只能记录为承诺或待办。",
        "【因果与文本】禁止提示词、before_state、after_state等元信息泄漏；禁止时间倒退、"
        "同一事件无理由重复、为了抵达大纲结果临时追加未经铺垫的成功事件。",
    ]
    if re.search(r"元|块|现金|资金|资产|收入|支出|成本|借款|债务|库存|货权|回款|应收|利润", text):
        rules.append(
            "【资金与资产】按期初余额＋实际收入－实际支出重算期末余额；逐笔核对本金、费用、"
            "债务、库存和所有权。预留额度、签协议、待付款、未到账收入不得改变现金或资产；"
            "只有付款及相应凭证/交付完成后才更新账本。"
        )
    if re.search(r"订单|合同|客户|供应商|采购|生产|交期|交付|验收|定金|应收|货款|入库|发货", text):
        rules.append(
            "【合同与经营】核对订单确认、定金、采购、入库、生产、验收、交付、回款的先后关系；"
            "交期必须有双方确认的唯一起算点；验收是交付前义务，逾期责任需单独约定；"
            "新订单不能自动消除旧应收款、旧债或现金流压力。"
        )
    if re.search(r"股票|证券|持仓|建仓|卖出|买入|停牌|复牌|比赛账户|模拟盘|实盘|融资|融券|上市", text):
        rules.append(
            "【证券交易】区分模拟与现实账户，逐笔核对委托、成交、持仓、费用和余额；"
            "空仓后未买入不得卖出，同日停复牌不得矛盾，统一本金和杠杆规则必须对所有人一致；"
            "真实公司与市场制度必须符合故事年份。"
        )
    if re.search(r"厂|产线|设备|工艺|损耗|材料|元件|质量|首件|返工", text):
        rules.append(
            "【生产制造】核对材料到位、工艺确认、首件验证、批量生产、质量验收和出货顺序；"
            "产能、损耗、成本和交期必须相互匹配，未入库材料不得视为可用库存。"
        )
    if re.search(r"手机|电话|传真|互联网|交通|汽车|火车|飞机|制度|监管|公司|银行", text):
        rules.append(
            "【时代与权限】设备、通信、交通、公司状态和制度符合故事年份；"
            "角色不得越权现场完成贷款、审批、任命、定罪或查封。"
        )
    return "\n".join(f"{index}. {rule}" for index, rule in enumerate(rules, 1))


class AIService:
    def __init__(self) -> None:
        self._pricing: dict[tuple[str, str], tuple[float, float]] = {}

    @staticmethod
    def web_config(provider: str):
        if provider not in {"deepseek", "chatgpt"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WEB_AI_PROVIDER_INVALID:免费模式仅支持 DeepSeek 或 ChatGPT 网页版。",
            )
        return SimpleNamespace(
            name=f"{provider} 网页版",
            base_url=settings.MINITEXT_WEB_AI_URL.rstrip("/") + "/v1",
            api_key="web-login",
            model=provider,
            input_price_cny=0,
            output_price_cny=0,
        )

    @staticmethod
    def _transport_error_detail(exc: Exception) -> str:
        error_name = type(exc).__name__
        if isinstance(exc, httpx.ReadTimeout):
            return (
                "AI_RESPONSE_TIMEOUT:模型响应超过 300 秒。为避免重复计费，本次未自动重试；"
                "已保存的章节不会丢失，请稍后从失败的章节范围继续生成。"
            )
        if isinstance(exc, httpx.ReadError):
            return (
                "AI_RESPONSE_INTERRUPTED:AI 服务已接受请求，但返回内容时网络连接中断"
                f"（{error_name}）。接口方可能已经计费，为避免重复扣费，本次未自动重试；"
                "请稍后从失败的章节范围继续生成。"
            )
        if isinstance(exc, httpx.ConnectTimeout):
            return "AI_CONNECT_TIMEOUT:连接 AI 服务超时，请检查网络、接口地址或代理后重试。"
        if isinstance(exc, httpx.ConnectError):
            return (
                f"AI_CONNECT_FAILED:无法连接 AI 服务（{error_name}），"
                "请检查网络、接口地址、代理和防火墙。"
            )
        if isinstance(exc, httpx.RemoteProtocolError):
            return (
                f"AI_PROTOCOL_ERROR:AI 服务返回协议中断（{error_name}）。"
                "为避免重复计费，本次未自动重试。"
            )
        message = str(exc).strip() or repr(exc)
        return f"AI_CALL_FAILED:{error_name}: {message}"

    async def _call_web_adapter(
        self,
        messages: list[dict],
        base_url: str,
        api_key: str,
        model: str,
        json_mode: bool,
    ) -> str:
        """Use the durable browser task endpoint for every free-web AI call."""
        instruction = "\n\n".join(
            f"[{str(message.get('role', 'user')).upper()}]\n{message.get('content', '')}"
            for message in messages
        )
        if json_mode:
            output_schema = {"type": "object", "additionalProperties": True}
        else:
            output_schema = {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
                "additionalProperties": False,
            }
            instruction += "\n\n请把最终正文或剧本完整放入 content 字段，保留自然段换行。"
        # Cache namespace v3 invalidates responses produced before browser
        # recovery compared the prompt tail.  Those caches could contain a
        # prose draft under an audit/revision request key.
        fingerprint = hashlib.sha256(
            f"web-call-v3\0{model}\0{json_mode}\0{instruction}".encode("utf-8")
        ).hexdigest()
        payload = {
            "requestId": f"ai-{fingerprint[:40]}",
            "idempotencyKey": f"ai-{fingerprint}",
            "provider": model,
            "input": {},
            "taskType": "json_transform" if json_mode else "custom",
            "instruction": instruction,
            "outputSchema": output_schema,
            "mode": "fast" if model == "deepseek" else "current",
            "cleanup": "none",
            "timeoutMs": 720_000,
            "maxAttempts": 2,
        }
        timeout = httpx.Timeout(connect=20.0, read=780.0, write=90.0, pool=20.0)
        try:
            body = await self._post_web_task(base_url, api_key, payload, timeout)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"WEB_AI_ADAPTER_ERROR:HTTP {exc.response.status_code}: {exc.response.text[:800]}",
            )
        if not body.get("success") or not isinstance(body.get("data"), dict):
            error = body.get("error") or {}
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"WEB_AI_FAILED:{error.get('code', 'UNKNOWN')}:{error.get('message', '网页版 AI 生成失败')}",
            )
        data = body["data"]
        if json_mode:
            return json.dumps(data, ensure_ascii=False)
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="WEB_AI_EMPTY_CONTENT:网页版 AI 未返回正文")
        return content.strip()

    async def _post_web_task(
        self,
        base_url: str,
        api_key: str,
        payload: dict,
        timeout: httpx.Timeout,
    ) -> dict:
        """Submit once; if the socket drops, reclaim the same durable result.

        The status endpoint never starts a model generation. This makes a
        ReadError safe to recover from without repeating the browser prompt or
        incurring a second generation cost.
        """
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        root = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(root + "/generate", json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.TransportError as exc:
            logger.warning(
                "Web AI response connection interrupted; reclaiming idempotent result key=%s error=%s",
                payload.get("idempotencyKey"),
                type(exc).__name__,
            )

        deadline = asyncio.get_running_loop().time() + min(
            840.0,
            max(90.0, float(payload.get("timeoutMs") or 720_000) / 1000 + 60),
        )
        missing_checks = 0
        last_error: Exception | None = None
        status_timeout = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0)
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(2 if missing_checks < 3 else 5)
            try:
                async with httpx.AsyncClient(timeout=status_timeout) as client:
                    response = await client.post(root + "/generate/status", json=payload, headers=headers)
                    response.raise_for_status()
                    state = response.json()
                if state.get("status") == "completed" and isinstance(state.get("response"), dict):
                    logger.info("Reclaimed completed web AI result key=%s", payload.get("idempotencyKey"))
                    return state["response"]
                if state.get("status") == "running":
                    missing_checks = 0
                    continue
                missing_checks += 1
                if missing_checks >= 3:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "WEB_AI_RESULT_NOT_FOUND:网页生成连接中断，适配器中也未找到正在运行或已缓存的任务。"
                            "为避免重复生成，本次没有重新提交；已保存的检查点不会丢失。"
                        ),
                    )
            except HTTPException:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                continue
        detail = self._transport_error_detail(last_error or RuntimeError("result reclaim timed out"))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WEB_AI_RESULT_RECLAIM_TIMEOUT:{detail}",
        )

    async def _call(
        self,
        messages: list[dict],
        base_url: str,
        api_key: str,
        model: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        if base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            return await self._call_web_adapter(messages, base_url, api_key, model, json_mode)
        url = base_url.rstrip("/") + "/chat/completions"
        payload = {"model": model, "messages": messages}
        # DeepSeek V4 defaults to thinking mode. For this application the
        # requested output is the deliverable prose/JSON itself; allowing CoT
        # to consume max_tokens can leave message.content empty. Explicitly use
        # non-thinking mode for stable, cost-bounded generation and audits.
        if "deepseek" in model.lower():
            payload["thinking"] = {"type": "disabled"}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode and ("gpt" in model or "deepseek" in model):
            payload["response_format"] = {"type": "json_object"}
        timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Provider-side overload happens before a usable completion is
                # returned, so retrying these response codes is safe and avoids
                # throwing away the chapter segment already checkpointed. Do
                # not retry read interruptions/timeouts: the provider may have
                # generated (and billed) the completion already.
                retryable_statuses = {429, 502, 503, 504}
                retry_delays = (2, 5, 10)
                for request_attempt in range(len(retry_delays) + 1):
                    try:
                        resp = await client.post(
                            url,
                            json=payload,
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        )
                    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                        # A connection/DNS/TLS handshake failure happens before
                        # the provider accepts a completion, so a bounded retry
                        # is safe and does not duplicate a billed generation.
                        if request_attempt >= len(retry_delays):
                            raise
                        delay = retry_delays[request_attempt]
                        logger.warning(
                            "AI connection failed before request acceptance error=%s retry=%s/%s delay=%ss",
                            type(exc).__name__,
                            request_attempt + 1,
                            len(retry_delays),
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if resp.status_code not in retryable_statuses:
                        break
                    if request_attempt >= len(retry_delays):
                        break
                    delay = retry_delays[request_attempt]
                    logger.warning(
                        "AI provider temporarily unavailable status=%s retry=%s/%s delay=%ss",
                        resp.status_code,
                        request_attempt + 1,
                        len(retry_delays),
                        delay,
                    )
                    await asyncio.sleep(delay)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage") or {}
                input_price, output_price = self._pricing.get(
                    (base_url.rstrip("/"), model),
                    (0.0, 0.0),
                )
                ai_usage_service.record(
                    model=data.get("model") or model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    input_price_cny=input_price,
                    output_price_cny=output_price,
                )
                choice = data["choices"][0]
                message = choice.get("message") or {}
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    reasoning = message.get("reasoning_content") or ""
                    finish_reason = choice.get("finish_reason") or "unknown"
                    logger.warning(
                        "AI returned empty content model=%s finish_reason=%s reasoning_length=%s completion_tokens=%s",
                        data.get("model") or model,
                        finish_reason,
                        len(reasoning),
                        usage.get("completion_tokens", 0),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "AI_EMPTY_CONTENT:AI 接口返回了空正文，已停止本次生成，未继续重复调用。"
                            f" finish_reason={finish_reason}"
                        ),
                    )
                return content
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            body = e.response.text[:1000]
            if status_code == 429:
                detail = f"AI_RATE_LIMITED:AI 接口请求过于频繁或额度受限，请稍后重试。{body}"
            elif status_code in (401, 403):
                detail = f"AI_AUTH_FAILED:API Key 无效或没有模型权限。{body}"
            elif status_code == 402:
                detail = f"AI_BALANCE_INSUFFICIENT:AI 账户余额不足。{body}"
            elif status_code >= 500:
                detail = f"AI_PROVIDER_ERROR:AI 服务端暂时异常（HTTP {status_code}）。{body}"
            else:
                detail = f"AI_API_ERROR:AI 接口返回 HTTP {status_code}。{body}"
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
        except httpx.TransportError as e:
            detail = self._transport_error_detail(e)
            logger.warning("AI transport failure: %s", detail, exc_info=True)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
        except Exception as e:
            detail = self._transport_error_detail(e)
            logger.exception("Unexpected AI call failure: %s", detail)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    def _resolve(self, ai_config: AIConfig | None) -> tuple[str, str, str]:
        """Return (base_url, api_key, model) from config or settings fallback."""
        if ai_config:
            if not ai_config.base_url or not ai_config.model:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="AI_CONFIG_REQUIRED:AI 模型配置不完整，请进入“设置 → AI 模型配置”补充接口地址和模型名。",
                )
            self._pricing[(ai_config.base_url.rstrip("/"), ai_config.model)] = (
                float(getattr(ai_config, "input_price_cny", 0) or 0),
                float(getattr(ai_config, "output_price_cny", 0) or 0),
            )
            return ai_config.base_url, ai_config.api_key, ai_config.model
        if not settings.AI_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI_CONFIG_REQUIRED:此功能需要使用 AI 模型。请先进入“设置 → AI 模型配置”，添加接口地址、API Key 和模型名，并设为默认配置。",
            )
        return settings.AI_BASE_URL, settings.AI_API_KEY, settings.AI_MODEL

    async def analyze_structured_text(
        self,
        system_prompt: str,
        user_prompt: str,
        ai_config: AIConfig | None = None,
        max_tokens: int = 6000,
    ) -> dict:
        """Run one bounded structured analysis for assistant-side reports."""
        base_url, api_key, model = self._resolve(ai_config)
        # The local browser adapter has a durable /generate endpoint. Use it
        # for long manuscript inspections so the browser can keep waiting past
        # the normal API timeout, persist the completed answer, and return the
        # same result after a desktop/network interruption instead of starting
        # another costly generation.
        if base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            fingerprint = hashlib.sha256(
                f"{model}\0{system_prompt}\0{user_prompt}".encode("utf-8")
            ).hexdigest()
            payload = {
                "requestId": f"manuscript-{fingerprint[:40]}",
                "idempotencyKey": f"manuscript-{fingerprint}",
                "provider": model,
                "input": {},
                "taskType": "quality_review",
                "instruction": f"{system_prompt}\n\n{user_prompt}",
                "outputSchema": {"type": "object", "additionalProperties": True},
                "mode": "fast" if model == "deepseek" else "current",
                "cleanup": "none",
                "timeoutMs": 720_000,
                "maxAttempts": 2,
            }
            timeout = httpx.Timeout(connect=20.0, read=780.0, write=90.0, pool=20.0)
            try:
                body = await self._post_web_task(base_url, api_key, payload, timeout)
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"WEB_AI_ADAPTER_ERROR:HTTP {exc.response.status_code}: {exc.response.text[:800]}",
                )
            if not body.get("success") or not isinstance(body.get("data"), dict):
                error = body.get("error") or {}
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"WEB_AI_INSPECTION_FAILED:{error.get('code', 'UNKNOWN')}:"
                        f"{error.get('message', '网页版 AI 未返回完整体检报告')}"
                    ),
                )
            return body["data"]
        raw = await self._call(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            base_url,
            api_key,
            model,
            json_mode=True,
            max_tokens=max_tokens,
        )
        return self._parse_json_response(raw, "manuscript inspection")

    async def generate_outline(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_episodes: int,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate outline JSON string."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = creative_prompt("short_outline", system_prompt)
        user_msg = (
            f"请为以下短剧创作分集大纲，共 {total_episodes} 集。\n"
            f"剧名：{title}\n"
            f"类型：{genre or '不限'}\n"
            f"故事梗概：{synopsis}\n\n"
            "请以纯 JSON 格式返回，格式如下（不要有任何其他文字）：\n"
            '{"total_episodes": N, "theme": "核心主题", "episodes": ['
            '{"episode_number": 1, "title": "集标题", "synopsis": "本集简介"}, ...]}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, "outline")
        return json.dumps(parsed, ensure_ascii=False)

    async def generate_script(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate script content."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = creative_prompt("short_script", system_prompt)
        user_content = ""
        if context:
            user_content += f"项目背景：\n{context}\n\n"
        user_content += f"请根据以下要求生成本集剧本：\n{prompt}"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_content}]
        raw = await self._call(messages, base_url, api_key, model)
        return normalize_short_script(raw)

    async def improve_script(
        self,
        content: str,
        instruction: str,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Improve existing script content."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = creative_prompt("script_improve")
        user_msg = f"原剧本：\n{content}\n\n优化指令：{instruction}\n\n请输出优化后的完整剧本。"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        return await self._call(messages, base_url, api_key, model)

    def _parse_json_response(self, raw: str, context: str) -> dict:
        """Parse JSON from AI response, stripping markdown fences if needed."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()

        candidates = [cleaned]
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidates.append(cleaned[first_brace:last_brace + 1])

        for candidate in candidates:
            # Models occasionally leave trailing commas even in JSON mode.
            variants = [
                candidate,
                re.sub(r",\s*([}\]])", r"\1", candidate),
            ]
            for variant in variants:
                try:
                    parsed = json.loads(variant)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI returned invalid JSON for {context}. Raw response: {raw[:300]}"
        )

    async def generate_story_roadmap(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Create the fixed whole-book stage contract used by every later call."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("roadmap")
        user = (
            f"小说名：{title}\n类型：{genre or '不限'}\n总章节数：{total_chapters}\n"
            f"故事梗概：{synopsis}\n\n"
            "请输出纯 JSON：\n"
            '{"total_chapters": 50, "protagonist": {"name": "主角名", "identity": "初始身份", '
            '"initial_state": {"wealth": "初始财富", "assets": [], "career": "初始职业", '
            '"abilities": [], "relationships": []}}, '
            '"dialogue_profiles": {"角色名": {"languages": ["普通话"], '
            '"forbidden_languages": ["粤语"], "default_register": "日常口吻", '
            '"speech_habits": [], "addresses": {"其他角色名": "默认称呼"}}}, '
            '"relationship_states": [{"character_a": "角色A", "character_b": "角色B", '
            '"status": "当前关系", "a_calls_b": "称呼", "b_calls_a": "称呼", '
            '"effective_chapter": 1, "change_condition": "允许改变称呼的剧情条件"}], "stages": ['
            '{"id": "S1", "name": "阶段名", "start_chapter": 1, "end_chapter": 10, '
            '"goal": "阶段目标", "entry_condition": "进入条件", "exit_condition": "完成标志", '
            '"required_plot_points": ["必须发生的情节"], "state_gain": "不可逆获得或失去", '
            '"transition_to_next": "自然进入下一阶段的因果事件"}]}'
        )
        last_error = "roadmap missing"
        for _ in range(3):
            raw = await self._call(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                base_url, api_key, model, json_mode=True,
            )
            roadmap = self._parse_json_response(raw, "story roadmap")
            stages = sorted(
                roadmap.get("stages") or [],
                key=lambda item: item.get("start_chapter", 0),
            )
            expected_start = 1
            valid = bool(stages)
            for stage in stages:
                start = stage.get("start_chapter")
                end = stage.get("end_chapter")
                if (
                    start != expected_start
                    or not isinstance(end, int)
                    or end < start
                    or not stage.get("entry_condition")
                    or not stage.get("exit_condition")
                ):
                    valid = False
                    break
                expected_start = end + 1
            if valid and expected_start == total_chapters + 1:
                roadmap["total_chapters"] = total_chapters
                roadmap["stages"] = stages
                return roadmap
            last_error = (
                "stage ranges must be continuous from chapter 1 through "
                f"chapter {total_chapters}, with entry and exit conditions"
            )
            user += f"\n\n上一次路线图无效：{last_error}。请完整重做。"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI failed to create a valid story roadmap: {last_error}",
        )

    async def audit_outline_candidate(
        self,
        synopsis: str,
        roadmap: dict,
        state_ledger: dict,
        canon_facts: list,
        previous_chapters: list[dict],
        candidate_chapters: list[dict],
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Audit an outline batch and return approved or a complete replacement."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("audit_outline")
        payload = {
            "synopsis": synopsis,
            "roadmap": roadmap,
            "state_ledger": state_ledger,
            "canon_facts": canon_facts,
            "previous_chapters": previous_chapters[-10:],
            "candidate_chapters": candidate_chapters,
        }
        user = (
            f"审核材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "输出纯 JSON："
            '{"approved": true, "issues": [], "revised_chapters": ['
            '{"chapter_number": 1, "title": "标题", "synopsis": "完整简介", '
            '"stage_id": "S1", "before_state": {}, "after_state": {}, '
            '"irreversible_facts": [], "transition": "与前后阶段的因果承接", '
            '"speech_constraints": ["Sam用带粤语习惯的表达并称陈远为陈生"], '
            '"relationship_changes": [], "address_changes": []}]}。'
            "若不通过，revised_chapters 必须包含本批全部章节的完整替换稿；"
            "若通过，也原样返回完整 candidate_chapters。"
        )
        last_error: HTTPException | None = None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(1, 3):
            raw = await self._call(messages, base_url, api_key, model, json_mode=True)
            try:
                return self._parse_json_response(raw, "outline continuity audit")
            except HTTPException as exc:
                last_error = exc
                messages = [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            user
                            + "\n\nThe previous response was not valid JSON. "
                            "Return exactly one JSON object without markdown, comments, or trailing commas."
                        ),
                    },
                ]
        raise last_error or HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an invalid outline audit response.",
        )

    async def revise_outline_candidate(
        self,
        synopsis: str,
        roadmap: dict,
        state_ledger: dict,
        canon_facts: list,
        previous_chapters: list[dict],
        candidate_chapters: list[dict],
        issues: list,
        ai_config: AIConfig | None = None,
    ) -> list[dict]:
        """Rewrite a rejected outline batch against the exact audit findings."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("outline")
        payload = {
            "synopsis": synopsis,
            "roadmap": roadmap,
            "state_ledger": state_ledger,
            "canon_facts": canon_facts[-100:],
            "previous_chapters": previous_chapters[-10:],
            "rejected_chapters": candidate_chapters,
            "audit_issues": issues,
        }
        user = (
            f"请修复以下未通过连续性审核的章节大纲：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "逐条落实 audit_issues 的 repair_instruction，并遵守：\n"
            "1. 章节必须处于路线图规定的 stage_id 和章节范围，不得提前进入下一阶段；\n"
            "2. before_state 必须继承上一章 after_state（首章继承 state_ledger），"
            "after_state 必须给出本章结束后的完整关键状态；\n"
            "3. 所有现金、资产、债务变化必须算得通，并在 synopsis 写明资金来源、支出和余额；\n"
            "4. 未解决冲突必须延续或在本章明确收束，不得无故消失；\n"
            "5. 不得更换主角、重置身份或删除已成立的不可逆事实；\n"
            "6. 必须遵守 dialogue_profiles 和 relationship_states；逐个角色写明"
            "speech_constraints。关系未发生变化时，relationship_changes/address_changes必须为空；"
            "发生变化时必须写明双方、旧称呼、新称呼、原因和生效章节。\n"
            "只输出纯 JSON，且必须返回原批次全部章节："
            '{"chapters":[{"chapter_number":1,"title":"标题","synopsis":"完整简介",'
            '"stage_id":"S1","before_state":{"cash":"变化前现金","assets":[],"open_conflicts":[]},'
            '"after_state":{"cash":"变化后现金","assets":[],"open_conflicts":[]},'
            '"irreversible_facts":[],"transition":"承上启下的因果",'
            '"speech_constraints":[],"relationship_changes":[],"address_changes":[]}]}'
        )
        raw = await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url,
            api_key,
            model,
            json_mode=True,
        )
        parsed = self._parse_json_response(raw, "outline revision")
        chapters = parsed.get("chapters") or parsed.get("revised_chapters") or []
        if isinstance(chapters, dict):
            chapters = list(chapters.values())
        if not isinstance(chapters, list):
            return []
        return [item for item in chapters if isinstance(item, dict)]

    async def audit_chapter_candidate(
        self,
        chapter_number: int,
        chapter_outline: dict,
        content: str,
        roadmap: dict,
        state_ledger: dict,
        canon_facts: list,
        previous_ending: str,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Return a strict pass/fail review. A failed draft is never persisted."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("audit_draft")
        payload = {
            "chapter_number": chapter_number,
            "chapter_outline": chapter_outline,
            "roadmap": roadmap,
            "state_ledger": state_ledger,
            "canon_facts": canon_facts[-100:],
            "previous_ending": previous_ending,
            "candidate_content": content,
        }
        focus_rules = _audit_focus_rules(payload)
        user = (
            f"审核材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            '只输出 JSON：{"approved": true, "issues": [], '
            '"summary": "审核结论与本章状态变化摘要"}。'
            "issues 每项必须包含 type、evidence、conflict_with、repair_instruction。\n"
            "必须按以下动态选择的模块逐项审核，不得仅凭文风流畅判通过：\n"
            f"{focus_rules}\n"
            "数字审核必须遵守：现金余额与总资产不是同一概念；购买资产后现金减少、资产增加，"
            "只有现金加资产再扣负债后的净资产无法闭合时才判错。冻结申购款、实际获配成本、"
            "未获配退款和未使用余额必须分别核算，不得强迫现金余额等于章初总资产。\n"
            "若大纲、状态账本和不可逆事实没有给出某个价格、股数或比例，不得把模型自行编造的"
            "任一数字指定为权威答案；应要求删除不必要的精确数字，或统一采用正文中明确引用的"
            "同一份正式凭证，并验证单价×数量＝金额、章初净资产＋收入－费用＝章末净资产。\n"
            "结构审核必须逐项确认：正文结尾不是半句话且引号闭合；同一场景、核账、交稿、签约、"
            "收款不得重复执行；人物离场后不得无过渡回到同一地点；后五章边界事件只能铺垫，"
            "不得在本章提前完成。发现任一重复、截断或未来事件越界，必须判为不通过。\n"
            "任一项不成立，approved 必须为 false，并引用正文原句作为 evidence。\n"
            "输出必须精简：最多返回3个最严重且互不重复的问题；每条 evidence 不超过80字，"
            "repair_instruction 不超过100字，summary 不超过120字。禁止输出思考过程、"
            "逐项检查记录或正文复述，确保JSON完整闭合。"
        )
        raw = await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url, api_key, model, json_mode=True,
        )
        return self._parse_json_response(raw, "chapter continuity audit")

    async def revise_chapter_candidate(
        self,
        original_content: str,
        issues: list,
        context: str,
        prompt: str,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Repair only the rejected draft; the result must be audited again."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("draft")
        user = (
            f"正史背景与硬约束：\n{context}\n\n"
            f"本章任务：\n{prompt}\n\n"
            f"未通过审核的问题：\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"待返修正文：\n{original_content}\n\n"
            "请按每条 repair_instruction 完整重写本章。不得用一句解释掩盖冲突；"
            "必须在情节中建立充分因果。若问题包含 length/字数，修订后的正文必须控制在"
            "4500—5500字，硬性范围4200—6200字，删除重复回顾与同义复述但保留关键行动和证据。"
            "只输出修订后的小说正文，不得附带修改说明或字数说明。"
        )
        return await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url, api_key, model,
        )

    async def extract_canon_update(
        self,
        chapter_number: int,
        chapter_title: str,
        content: str,
        existing_ledger: dict,
        existing_facts: list,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Build the full post-chapter ledger only after the draft passed review."""
        base_url, api_key, model = self._resolve(ai_config)
        # The model returns only this chapter's delta. Re-emitting the complete
        # historical ledger grows without bound and eventually truncates JSON.
        protagonist = existing_ledger.get("protagonist", {})
        compact_state = {
            "current_chapter": existing_ledger.get("current_chapter"),
            "time_place": existing_ledger.get("time_place", ""),
            "protagonist": {
                key: protagonist.get(key)
                for key in (
                    "name", "aliases", "identity", "career", "organization",
                    "authority", "location", "current_goal", "wealth", "cash",
                    "assets", "debts", "injuries", "relationships", "promises",
                    "open_conflicts",
                )
                if key in protagonist
            },
            "supporting_characters": existing_ledger.get("supporting_characters", [])[-40:],
            "dialogue_profiles": existing_ledger.get("dialogue_profiles", {}),
            "relationship_states": existing_ledger.get("relationship_states", [])[-40:],
            "recent_transactions": existing_ledger.get("transaction_ledger", [])[-20:],
            "open_commitments": [
                item for item in existing_ledger.get("commitments", [])[-40:]
                if isinstance(item, dict) and item.get("status") in (None, "", "open", "待执行")
            ],
            "open_plot_threads": [
                item for item in existing_ledger.get("plot_threads", [])[-30:]
                if isinstance(item, dict) and item.get("status") in (None, "", "open")
            ],
        }
        delta_payload = {
            "chapter_number": chapter_number,
            "chapter_title": chapter_title,
            "previous_state": compact_state,
            "recent_irreversible_facts": existing_facts[-40:],
            "approved_content": content,
        }
        delta_user = (
            "根据已审核正文，只提取本章相对 previous_state 发生的变化。"
            "禁止复述完整历史账本，禁止从大纲猜测未发生事件。\n"
            f"材料：{json.dumps(delta_payload, ensure_ascii=False)}\n"
            "只输出单行紧凑JSON："
            '{"state_patch":{"current_chapter":1,"time_place":"",'
            '"protagonist":{},"supporting_characters":[],"dialogue_profiles":{},'
            '"relationship_states":[]},'
            '"structured_appends":{"asset_accounts":[],"transaction_ledger":[],'
            '"item_custody":[],"timeline":[],"commitments":[],"plot_threads":[],'
            '"knowledge_boundaries":[]},'
            '"new_irreversible_facts":[],"fact_status_updates":[]}。'
            "state_patch只写发生变化的字段；金额流水必须有正文证据和reconciled；"
            "transaction_ledger只记录主角本人拥有的现金/资产变化；公司、工厂、贸易部、客户账户的货款、定金和采购款不得改变主角cash_change。"
            "若证据写明由公司账户结算、个人未垫付、不经手或分文未沾，则cash_change必须为0，并写personal_cash_effect=false；"
            "不得用未列明金额的此前收入、其他进账或零散收入凑平期末余额；"
            "JSON必须完整闭合，不要Markdown和解释。"
        )
        delta_messages = [
            {"role": "system", "content": novel_skill_prompt("canon")},
            {"role": "user", "content": delta_user},
        ]
        parsed_delta = None
        last_error = None
        for attempt in range(2):
            raw_delta = await self._call(
                delta_messages,
                base_url,
                api_key,
                model,
                json_mode=True,
                max_tokens=4000,
            )
            try:
                parsed_delta = self._parse_json_response(raw_delta, "canon ledger delta")
                break
            except HTTPException as exc:
                last_error = exc
                logger.warning("Invalid canon delta JSON attempt=%s/2 length=%s", attempt + 1, len(raw_delta))
        if parsed_delta is None:
            assert last_error is not None
            raise last_error

        updated = json.loads(json.dumps(existing_ledger, ensure_ascii=False))

        def merge_dict(target: dict, patch: dict) -> None:
            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    merge_dict(target[key], value)
                else:
                    target[key] = value

        state_patch = parsed_delta.get("state_patch")
        if isinstance(state_patch, dict):
            merge_dict(updated, state_patch)
        updated["current_chapter"] = chapter_number

        appends = parsed_delta.get("structured_appends")
        if isinstance(appends, dict):
            for field in (
                "asset_accounts", "transaction_ledger", "item_custody", "timeline",
                "commitments", "plot_threads", "knowledge_boundaries",
            ):
                values = appends.get(field)
                if isinstance(values, list):
                    target = updated.setdefault(field, [])
                    if not isinstance(target, list):
                        target = []
                        updated[field] = target
                    target.extend(item for item in values if isinstance(item, dict))

        return {
            "state_ledger": updated,
            "new_irreversible_facts": parsed_delta.get("new_irreversible_facts", []),
            "fact_status_updates": parsed_delta.get("fact_status_updates", []),
        }

        # Legacy full-ledger protocol retained below for migration reference;
        # execution returns above through the bounded delta protocol.
        system = novel_skill_prompt("canon")
        payload = {
            "chapter_number": chapter_number,
            "chapter_title": chapter_title,
            "existing_state_ledger": existing_ledger,
            "existing_irreversible_facts": existing_facts[-100:],
            "approved_content": content,
        }
        user = (
            f"正史更新材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "输出纯 JSON："
            '{"state_ledger": {"current_chapter": 1, "time_place": "", '
            '"protagonist": {"name": "", "identity": "", "career": "", "wealth": "", '
            '"cash": "", "assets": [], "debts": [], "abilities": [], "reputation": "", '
            '"injuries": [], "relationships": [], "knowledge": [], "items": [], '
            '"promises": [], "open_conflicts": []}, "supporting_characters": [], '
            '"dialogue_profiles": {"角色名": {"languages": [], "forbidden_languages": [], '
            '"default_register": "", "speech_habits": [], "addresses": {"其他角色": "称呼"}, '
            '"address_history": [{"target": "角色", "old": "旧称呼", "new": "新称呼", '
            '"effective_chapter": 1, "reason": "正文事件"}]}}, '
            '"relationship_states": [{"character_a": "", "character_b": "", "status": "", '
            '"a_calls_b": "", "b_calls_a": "", "effective_chapter": 1, "reason": ""}]}, '
            '"new_irreversible_facts": [{"chapter": 1, "type": "wealth|identity|asset|ability|'
            'relationship|time|event", "fact": "不可逆事实", "cause": "正文原句或可核算依据"}]}。'
            "必须只依据 approved_content 提取，不得复制大纲中的未发生结果；"
            "现金、持仓、债务和物品必须按正文实际交易重算；若正文没有发生，禁止写入账本。"
        )
        user += (
            "\n结构化账本版本必须为2，并完整返回以下状态，不能只返回摘要："
            "\n1. protagonist与每个supporting_characters：canonical_name、aliases、身份、职业、组织、权限、"
            "当前位置、当前目标、知情范围、未知边界、持有物、资产、债务、伤势、最后出场章节；"
            "\n2. dialogue_profiles：语言、禁止语言、口吻、习惯及说话者到被称呼者的定向称呼；"
            "\n3. relationship_states：双向关系、双向称呼、生效章节和变化原因；"
            "\n4. asset_accounts与transaction_ledger：章初余额、逐笔收入/支出/借款/还款/买卖、数量、"
            "单价、费用、交易对手、章末余额、正文证据；无法核算时标记reconciled=false，禁止猜数字；"
            "\n5. item_custody：物品、持有人、取得/转移章节、当前位置和状态；"
            "\n6. timeline：时间、地点、出发地、目的地、交通方式、耗时和参与者；"
            "\n7. knowledge_boundaries：谁知道什么、从何得知、何章得知、谁明确不知道；"
            "\n8. commitments与plot_threads：承诺/冲突/伏笔的open、fulfilled、failed或superseded状态，"
            "截止时间、责任人、完成依据；"
            "\n9. new_irreversible_facts必须含status、effective_chapter、entities、evidence、importance。"
            "\n10. 若旧事实已履约、失败、失效或被替代，返回fact_status_updates："
            "[{fact_id,status,reason,effective_chapter,superseded_by}]；禁止删除旧事实。"
            "\n历史字段继续保留；同一人物必须按canonical_name和aliases合并，严禁重复建档。"
        )
        user += (
            "\n输出必须是单行紧凑 JSON，不要缩进、不要 Markdown、不要解释；"
            "优先保证 JSON 完整闭合，禁止在字符串或数组中途停止。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: HTTPException | None = None
        # Retry only ledger serialization when the provider truncates JSON.
        # Approved prose stays in its checkpoint and is not regenerated.
        for ledger_attempt, token_limit in enumerate((7000, 8000), 1):
            raw = await self._call(
                messages,
                base_url,
                api_key,
                model,
                json_mode=True,
                max_tokens=token_limit,
            )
            try:
                return self._parse_json_response(raw, "canon ledger update")
            except HTTPException as exc:
                last_error = exc
                logger.warning(
                    "Invalid canon ledger JSON attempt=%s/2 length=%s; retrying ledger extraction only",
                    ledger_attempt,
                    len(raw),
                )
                if ledger_attempt == 1:
                    messages = messages + [{
                        "role": "user",
                        "content": (
                            "上一次账本 JSON 未完整闭合。请重新从头输出更紧凑的完整 JSON；"
                            "不要解释，不得省略 state_ledger、protagonist 和 "
                            "new_irreversible_facts。"
                        ),
                    }]
        assert last_error is not None
        raise last_error

    async def repair_canon_coverage(
        self,
        chapter_number: int,
        content: str,
        current_ledger: dict,
        coverage_issues: list,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Extract only missing ledger records without regenerating prose."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("canon")
        payload = {
            "chapter_number": chapter_number,
            "coverage_issues": coverage_issues,
            "current_asset_accounts": current_ledger.get("asset_accounts", []),
            "current_chapter_transactions": [
                item
                for item in current_ledger.get("transaction_ledger", [])
                if isinstance(item, dict)
                and int(item.get("chapter") or 0) == chapter_number
            ],
            "approved_content": content,
        }
        user = (
            f"账本补录材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "正文已经通过审核，禁止改写正文。只补录 coverage_issues 指出的缺失流水。"
            "所有记录必须来自 approved_content 的明确事实；无法确定的金额写空字符串并设置 "
            "reconciled=false，禁止猜测。\n"
            "只输出 JSON："
            '{"asset_accounts": [], "transaction_ledger": [], "item_custody": [], '
            '"timeline": [], "commitments": [], "plot_threads": [], '
            '"knowledge_boundaries": []}。\n'
            f"每条新增记录都必须写 chapter={chapter_number}，交易流水还必须包含 type、"
            "amount、counterparty、evidence、reconciled；时间线必须包含 origin、"
            "destination、transport、sequence、evidence。"
        )
        raw = await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url,
            api_key,
            model,
            json_mode=True,
            max_tokens=4000,
        )
        return self._parse_json_response(raw, "canon coverage repair")

    async def _generate_chapters_range(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        start: int,
        end: int,
        theme: str,
        sys_msg: str,
        base_url: str,
        api_key: str,
        model: str,
        previous_chapters: list[dict] | None = None,
    ) -> tuple[list[dict], str]:
        """Generate chapters [start, end] as a single AI call. Returns list of chapter dicts."""
        theme_hint = f"\n核心主题（请保持一致）：{theme}" if theme else ""
        previous_chapters = previous_chapters or []
        start_progress = round((start - 1) / total_chapters * 100)
        end_progress = round(end / total_chapters * 100)
        remaining_chapters = max(total_chapters - end, 0)
        progress_hint = (
            "\n\n【全书进度坐标与剧情推进（与连续性同等重要）】\n"
            f"本批次位于全书约 {start_progress}%～{end_progress}% 的位置，"
            f"生成后还剩 {remaining_chapters} 章。\n"
            "必须先根据“故事梗概”识别其中按时间或因果排列的全部重要阶段、行业、目标和重大事件，"
            "再按总章数把它们合理分配到开篇、发展、中段、后段和结局。\n"
            "开篇1～5章只用于锁定主角身份、人物关系和世界观，不代表后续必须停留在开篇的剧情阶段；"
            "最近章节只用于保证因果承接，也不允许反复复制同一阶段、同一目标或同类事件。\n"
            "若梗概包含多个连续阶段（例如股票、楼市、互联网），必须让前一阶段产生明确成果或转折，"
            "并在合理章数内进入下一阶段，确保结局前覆盖全部阶段；不得因为强调连续性而长期原地打转。\n"
            "本批次既要承接上一章，又必须产生不可逆的新进展，并为梗概中的下一项尚未完成的重要阶段铺垫。\n"
        )
        anchor_chapters = previous_chapters[:5]
        recent_chapters = previous_chapters[-10:]
        continuity_chapters = {
            chapter["chapter_number"]: chapter
            for chapter in [*anchor_chapters, *recent_chapters]
            if chapter.get("chapter_number", 0) < start
        }
        continuity_hint = ""
        if continuity_chapters:
            continuity_json = json.dumps(
                list(continuity_chapters.values()),
                ensure_ascii=False,
            )
            continuity_hint = (
                "\n\n【已确定的正史大纲（不可改写）】\n"
                f"{continuity_json}\n"
                "必须延续上述主角、身份、核心目标、人物关系、时间线、资源状态、未解决冲突和上一章钩子。"
                "不得在本批次重新定义主角，不得另起一个无关故事，不得把新人物写成新的主角。"
                f"第 {start} 章必须直接承接第 {start - 1} 章的结果或钩子。"
            )
        count = end - start + 1
        user_msg = (
            f"请为以下小说创作第 {start}~{end} 章的章节大纲（共 {total_chapters} 章，本次只生成这 {count} 章）。\n"
            f"小说名：{title}\n"
            f"类型：{genre or '不限'}\n"
            f"故事大概：{synopsis}{theme_hint}{progress_hint}{continuity_hint}\n\n"
            "连续性硬性要求：全书默认只有同一位核心主角；除非原始故事大概明确指定群像或双主角，"
            "否则不得更换主角。新人物只能作为配角、对手或阶段人物，并必须由既有因果引入。"
            "每章的开端必须承接前章的结果，每章的变化必须进入下一章，禁止批次边界剧情重置。\n\n"
            f"严格只输出第 {start} 到第 {end} 章，纯 JSON，不要任何其他文字：\n"
            '{"total_chapters": ' + str(total_chapters) + ', "theme": "核心主题", "chapters": ['
            '{"chapter_number": ' + str(start) + ', "title": "章节标题", '
            '"synopsis": "写明冲突、推进、资金/资产变化依据、局部结果和章尾钩子的完整简介", '
            '"stage_id": "路线图阶段ID", '
            '"before_state": {"cash": "章初现金", "assets": [], "debts": [], '
            '"career": "章初职业", "open_conflicts": []}, '
            '"after_state": {"cash": "章末现金", "assets": [], "debts": [], '
            '"career": "章末职业", "open_conflicts": []}, '
            '"irreversible_facts": ["本章成立且后文不可随意推翻的事实"], '
            '"transition": "承接前章并引向下一章的具体因果", '
            '"speech_constraints": ["角色使用的语言、口吻以及对其他角色的固定称呼"], '
            '"relationship_changes": [], "address_changes": []}'
            + (', ...' if count > 1 else '') + ']}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, f"chapters {start}-{end}")
        return parsed.get("chapters", []), parsed.get("theme", theme)

    async def generate_novel_outline(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        start_chapter: int = 1,
        end_chapter: int | None = None,
        theme: str = "",
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
        previous_chapters: list[dict] | None = None,
    ) -> str:
        """Generate novel chapter outline for [start_chapter, end_chapter].
        On JSON parse failure, automatically falls back to chapter-by-chapter generation."""
        base_url, api_key, model = self._resolve(ai_config)
        end = end_chapter or total_chapters
        sys_msg = novel_skill_prompt("outline", system_prompt)

        all_chapters: list[dict] = []
        current_theme = theme

        # Try the whole range first; on failure fall back to one-by-one
        try:
            chapters, current_theme = await self._generate_chapters_range(
                title, genre, synopsis, total_chapters,
                start_chapter, end, current_theme, sys_msg, base_url, api_key, model,
                previous_chapters,
            )
            all_chapters = chapters
        except HTTPException as exc:
            # Only retry malformed model output. Authentication, networking and
            # configuration errors must reach the UI instead of becoming fake
            # "生成失败" outline placeholders.
            if not str(exc.detail).startswith("AI returned invalid JSON"):
                raise
            # Fallback: generate one chapter at a time
            continuity_chapters = list(previous_chapters or [])
            for ch_num in range(start_chapter, end + 1):
                for attempt in range(3):
                    try:
                        chapters, fetched_theme = await self._generate_chapters_range(
                            title, genre, synopsis, total_chapters,
                            ch_num, ch_num, current_theme, sys_msg, base_url, api_key, model,
                            continuity_chapters,
                        )
                        if chapters:
                            all_chapters.extend(chapters)
                            continuity_chapters.extend(chapters)
                            if not current_theme and fetched_theme:
                                current_theme = fetched_theme
                        break
                    except HTTPException as exc:
                        if not str(exc.detail).startswith("AI returned invalid JSON"):
                            raise
                        if attempt == 2:
                            # Give up on this chapter, insert placeholder
                            all_chapters.append({
                                "chapter_number": ch_num,
                                "title": f"第{ch_num}章",
                                "synopsis": "（生成失败，请手动补充）",
                            })

        result = {
            "total_chapters": total_chapters,
            "theme": current_theme,
            "chapters": all_chapters,
        }
        return json.dumps(result, ensure_ascii=False)

    async def generate_chapter(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate one complete 4500—5500-character chapter."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = novel_skill_prompt("draft", system_prompt)
        user_content = ""
        if context:
            user_content += f"小说背景：\n{context}\n\n"
        user_content += f"请根据以下要求生成本章内容：\n{prompt}"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_content}]
        return await self._call(messages, base_url, api_key, model)

    async def generate_chapter_segment(
        self,
        prompt: str,
        context: str,
        segment_index: int,
        total_segments: int,
        completed_content: str = "",
        ai_config: AIConfig | None = None,
        system_prompt: str | None = None,
        retry_feedback: list | None = None,
    ) -> str:
        """Generate one bounded scene segment so slow models can resume safely."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = novel_skill_prompt("draft", system_prompt)
        roles = {
            1: "完成开场、承接前章并建立本章核心冲突",
            2: "推进冲突、落实关键行动与因果变化",
            3: "完成高潮、结果核算、关系变化和章末钩子",
        }
        role = roles.get(segment_index, "继续推进并完成当前场景任务")
        prior = completed_content[-6000:] if completed_content else "（本章尚未生成前文）"
        user = (
            f"正史背景与硬约束：\n{context}\n\n"
            f"本章总任务：\n{prompt}\n\n"
            f"现在只生成第 {segment_index}/{total_segments} 段，职责：{role}。\n"
            "本段控制在1500—1850个中文字符；只输出可直接拼接的小说正文，"
            "不要输出章节标题、段号、创作说明、账本、大纲或审核意见。\n"
            "必须遵守人物称呼、语言、时间、地点、资产和不可逆事实；"
            "本段不得提前重复后续段落的结局。\n\n"
            "已生成正文中的场景均视为已经完成：不得重新核账、重新见同一人、重新提交同一稿件、"
            "重新签署同一合同或让已经离场的人无过渡回到原场景。"
            "第1、2段不得提前写章末总结；第3段必须从前文最后动作继续，补全结果和章末收束。"
            "每段必须以完整句子结束，所有引号、括号和书名号必须闭合。\n\n"
            f"已生成正文末尾（仅用于自然承接）：\n{prior}"
        )
        if retry_feedback:
            user += (
                "\n\n上一次候选段未被系统接纳，原因如下：\n"
                f"{json.dumps(retry_feedback, ensure_ascii=False)}\n"
                "本次必须避开这些问题，尤其不得重新执行前文已经完成的场景或任务。"
            )
        try:
            return await self._call(
                [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}],
                base_url,
                api_key,
                model,
                # DeepSeek Flash commonly exceeds the requested Chinese
                # character count when given a 1600-token ceiling. A 1250
                # ceiling keeps each checkpoint segment near 1500-1900
                # Chinese characters and the full chapter near 4500-5500.
                max_tokens=1500,
            )
        except HTTPException as exc:
            exc.detail = (
                f"STANDARD_SEGMENT_FAILED:标准模式第{segment_index}/{total_segments}段生成失败；"
                "此前完成的段落已保存，重新点击后将从本段继续。"
                f" 原因：{exc.detail}"
            )
            raise

    async def revise_chapter_segment(
        self,
        segment: str,
        segment_index: int,
        total_segments: int,
        issues: list,
        context: str,
        prompt: str,
        previous_tail: str = "",
        next_head: str = "",
        ai_config: AIConfig | None = None,
    ) -> str:
        """Repair only a faulty segment instead of paying to rewrite the whole chapter."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("draft")
        user = (
            f"正史背景与硬约束：\n{context}\n\n本章任务：\n{prompt}\n\n"
            f"当前是第{segment_index}/{total_segments}段，只修复这一段。\n"
            f"审核问题：\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"上一段末尾：\n{previous_tail[-1000:] or '（无）'}\n\n"
            f"待修段落：\n{segment}\n\n"
            f"下一段开头：\n{next_head[:1000] or '（无）'}\n\n"
            "若问题涉及价格、股数、金额、资产或时间顺序，这是跨段一致性问题：必须以本章大纲、"
            "状态账本、不可逆事实和同一份正式凭证为权威，修正本段所有相关数字与措辞。"
            "大纲未规定的精确数字不得擅自补造；确需保留时必须逐项满足单价×数量＝金额，"
            "并区分冻结款、实际成交成本、退款、现金余额与包含持仓的总资产。\n"
            "逐条落实 repair_instruction，保持与前后段自然衔接。"
            "修订后本段必须控制在1200—1900个中文字符，不得借返修扩写。"
            "只输出修订后的本段小说正文，不要输出解释、段号或审核结果。"
        )
        return await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url,
            api_key,
            model,
            max_tokens=1250,
        )

    async def update_knowledge_graph(
        self,
        chapter_content: str,
        chapter_number: int,
        chapter_title: str,
        existing_graph: str = "",
        ai_config: AIConfig | None = None,
    ) -> str:
        """Extract characters and events from chapter content, merge into existing graph."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = novel_skill_prompt("memory")
        existing_hint = f"\n\n已有连续性记忆（保留所有仍有效事实，在此基础上更新）：\n{existing_graph[:5000]}" if existing_graph else ""
        if len(chapter_content) <= 6000:
            chapter_excerpt = chapter_content
        else:
            chapter_excerpt = chapter_content[:3000] + "\n\n【中段省略】\n\n" + chapter_content[-3000:]
        user_msg = (
            f"请从以下第 {chapter_number} 章《{chapter_title}》的内容中，提取并更新人物关系。{existing_hint}\n\n"
            f"章节内容：\n{chapter_excerpt}\n\n"
            "提取规则：\n"
            "1. 只记录与主角有直接互动或关系的人物（主角本人必须包含），忽略与主角无关的次要人物。\n"
            "2. 删除只在一章中出现过一次、且对主角影响不重要的人物。\n"
            "3. 已有图谱中多次出现的人物必须保留并更新描述，不得删除。\n"
            "4. description 字段限制在30字以内，只写核心身份特征，不要罗列每章情节。\n"
            "5. events 记录本章造成的不可逆变化；open_threads 记录仍待兑现的危险、承诺、伏笔或期限。\n"
            "6. continuity 保存下一章不可违背的时间地点、伤势、资源物件、知识状态和承诺。\n\n"
            "请以纯 JSON 格式返回完整连续性记忆：\n"
            '{"characters": [{"name": "人物名", "role": "身份/角色", "description": "简要描述(30字内)", '
            '"relations": [{"target": "关联人物名", "relation": "关系描述"}]}], '
            '"events": [{"chapter": 1, "title": "事件名", "description": "不可逆变化"}], '
            '"open_threads": [{"thread": "未决线索", "last_chapter": 1, "status": "open"}], '
            '"continuity": {"time_place": "当前时空", "injuries": [], "items": [], "knowledge": [], "promises": []}}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, "knowledge graph")
        return json.dumps(parsed, ensure_ascii=False)


ai_service = AIService()
