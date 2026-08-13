(() => {
  "use strict";

  const dom = globalThis.MaliangDomDriver;
  const contract = globalThis.MaliangFanqieContract;
  if (!dom || !contract) throw new Error("Maliang Fanqie DOM driver was not loaded");

  const coded = (message, code, diagnostics = false) => Object.assign(new Error(message), {
    code, ...(diagnostics ? { diagnostics: dom.diagnostics() } : {}),
  });
  const compact = (value) => String(value || "").replace(/\s+/g, "");
  const includesAny = (value, words) => words.some((word) => value.includes(word));

  function riskReason() {
    const text = dom.bodyText();
    if (includesAny(text, contract.signals.risk)) return "番茄要求人工完成安全验证";
    if (/\/login(?:\/|$|\?)/.test(location.pathname + location.search)
      || /(^|\n)登录\s*\n\s*注册(\n|$)/.test(text)
      || includesAny(text, contract.signals.login) && !text.includes("退出登录")) return "番茄登录态已失效";
    return null;
  }

  function currentIdentity() {
    const authorNode = dom.query(contract.selectors.author_identity);
    const idNode = dom.query(contract.selectors.author_id);
    const text = dom.bodyText();
    const managementPage = /\/main\/writer\/(?:book-manage|chapter-manage|\d+\/publish)/.test(location.pathname);
    const authorVisible = dom.visible(authorNode);
    return {
      platform_author_name: (authorNode?.textContent || "").trim(),
      platform_author_id: idNode?.dataset?.authorId || idNode?.dataset?.userId || "",
      authenticated: !riskReason() && Boolean(authorVisible || text.includes("退出登录")
        || managementPage && /创作中心|作品管理/.test(text)),
      contract_version: contract.version,
    };
  }

  function identityMismatch(payload, identity) {
    return Boolean(
      payload.expected_author_id && identity.platform_author_id && payload.expected_author_id !== identity.platform_author_id
      || payload.expected_author_name && identity.platform_author_name && payload.expected_author_name !== identity.platform_author_name
    );
  }

  async function settledIdentity(payload = {}) {
    await dom.waitFor(() => {
      const identity = currentIdentity();
      if (riskReason()) return true;
      if (payload.expected_author_name || payload.expected_author_id)
        return Boolean(identity.platform_author_name || identity.platform_author_id);
      return identity.authenticated;
    }, contract.timeouts_ms.element);
    return currentIdentity();
  }

  function inferStatus(text) {
    const value = compact(text);
    for (const key of ["rejected", "reviewing", "scheduled", "draft", "published"])
      if (includesAny(value, contract.status_words[key])) return key;
    return "unknown";
  }

  function parseChapterRows(text = dom.bodyText()) {
    const rows = new Map();
    for (const line of String(text).split(/\r?\n/)) {
      const match = line.trim().match(/第\s*0*(\d+)\s*章\s*([^\n]*?)\s*$/);
      if (!match) continue;
      const number = Number(match[1]);
      const status = inferStatus(line);
      const words = Object.values(contract.status_words).flat().join("|");
      const title = match[2].split(new RegExp(words))[0].trim();
      const date = line.match(/(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})/);
      rows.set(number, {
        number, title, status,
        scheduled_at: status === "scheduled" && date
          ? new Date(Number(date[1]), Number(date[2]) - 1, Number(date[3]), 1).toISOString() : null,
      });
    }
    return [...rows.values()].sort((left, right) => left.number - right.number);
  }

  function listBooks() {
    const rows = [];
    for (const link of dom.queryAll(contract.selectors.book_links)) {
      const match = String(link.href || link.getAttribute("href") || "").match(/chapter-manage\/(\d+)(?:&([^?]+))?/);
      if (!match) continue;
      const container = link.closest('[class*="book"], [class*="work"], [class*="novel"], li, article') || link;
      const heading = container.querySelector('.info-content-title .hoverup,h1,h2,h3,h4,[class*="title"] [class*="hover"]');
      const encodedName = match[2] ? decodeURIComponent(match[2]) : "";
      rows.push({
        platform_book_id: match[1],
        book_name: (encodedName || heading?.textContent || link.textContent || "").trim().replace(/\s+/g, " "),
        status: inferStatus(container.textContent || ""),
      });
    }
    for (const node of dom.queryAll(contract.selectors.book_nodes)) {
      const bookId = String(node.dataset.bookId || node.dataset.bookid || "");
      if (!bookId) continue;
      rows.push({
        platform_book_id: bookId,
        book_name: (node.querySelector('[class*="title"],[class*="name"]')?.textContent || node.textContent || "").trim().replace(/\s+/g, " "),
        status: inferStatus(node.textContent || ""),
      });
    }
    return [...new Map(rows.map((row) => [row.platform_book_id, row])).values()];
  }

  function nextPageControl() {
    const controls = [...document.querySelectorAll('button,a,[role="button"],li')]
      .filter((node) => dom.visible(node)
        && !node.disabled
        && node.getAttribute("aria-disabled") !== "true"
        && !String(node.className || "").toLowerCase().includes("disabled"));
    const matches = controls.filter((node) => {
      const text = [node.innerText || "", node.getAttribute("aria-label") || "",
        node.getAttribute("title") || "", node.textContent || ""]
        .join(" ").replace(/\s+/g, " ").trim();
      return /下一页|下页|next|^\s*[>›»]\s*$/i.test(text);
    });
    return matches[matches.length - 1] || null;
  }

  async function listChapters() {
    const found = new Map();
    const seen = new Set();
    let complete = false;
    for (let page = 0; page < 80; page += 1) {
      const marker = compact(dom.bodyText());
      if (seen.has(marker)) break;
      seen.add(marker);
      for (const row of parseChapterRows()) found.set(row.number, row);
      const next = nextPageControl();
      if (!next) { complete = true; break; }
      dom.click(next);
      await dom.delay(1200);
    }
    return {
      chapters: [...found.values()].sort((left, right) => left.number - right.number),
      complete,
    };
  }

  function metadataValues(metadata) {
    const tags = (metadata.tags || []).map((tag) => typeof tag === "object"
      ? [tag.parent?.name || tag.parent, tag.child?.name || tag.child].filter(Boolean)
      : String(tag).split(">").map((item) => item.trim()).filter(Boolean));
    const protagonists = (metadata.protagonists || metadata.protagonist_names || []).map(String).filter(Boolean);
    const readerValue = typeof metadata.target_reader === "object"
      ? metadata.target_reader?.label || metadata.target_reader?.value : metadata.target_reader || metadata.gender;
    const tagCounts = new Map();
    for (const tag of tags) tagCounts.set(tag[0], (tagCounts.get(tag[0]) || 0) + 1);
    if (tagCounts.get("主分类") !== 1) throw new Error("作品标签必须且只能包含一个主分类");
    for (const [parent, count] of tagCounts) if (parent !== "主分类" && count > 2)
      throw new Error(`${parent}标签最多选择两个`);
    return {
      intro: String(metadata.intro || metadata.description || metadata.synopsis || "").trim(),
      tags, protagonists,
      reader: [2, "2", "女频", "female"].includes(readerValue) ? "女频" : [1, "1", "男频", "male"].includes(readerValue) ? "男频" : "",
    };
  }

  async function createBook(payload) {
    const resumedBookId = location.href.match(/chapter-manage\/(\d+)/)?.[1];
    if (resumedBookId) return { platform_book_id: resumedBookId, book_name: payload.book_name, resumed_after_navigation: true };
    const before = listBooks();
    if (before.some((item) => item.book_name === payload.book_name)) throw new Error("同名作品已存在，请选择已有作品");
    for (let step = 0; step < 3 && !dom.query(contract.selectors.book_name); step += 1) {
      const preparedEntry = dom.action(["创建书本"]);
      const entry = preparedEntry || dom.action(contract.actions.create_book, document, { exact: false });
      if (!entry) break;
      if (entry.matches(".write-button")) {
        dom.hover(entry);
        await dom.delay(500);
        continue;
      }
      if (entry.tagName === "A" && entry.href) { entry.removeAttribute("target"); location.href = entry.href; return new Promise(() => {}); }
      dom.click(entry);
      await dom.delay(800);
    }
    const name = await dom.waitFor(() => dom.query(contract.selectors.book_name));
    if (!name) throw coded("番茄建书页结构已变化，找不到书名输入框", "ADAPTER_OUTDATED", true);

    const values = metadataValues(payload.metadata || {});
    if (compact(values.intro).length < 50) throw new Error("作品简介少于 50 字");
    if (!values.reader) throw new Error("作品资料缺少明确的男频/女频");
    if (!values.tags.length || values.tags.some((tag) => tag.length < 2)) throw new Error("作品标签必须包含父级>二级标签");
    if (!values.protagonists.length) throw new Error("作品资料缺少主角名");
    if (!payload.cover_file?.data_base64) throw new Error("作品资料缺少可用封面");

    dom.setField(name, payload.book_name);
    const reader = dom.action([values.reader]);
    if (!reader) throw coded(`创建页未找到${values.reader}选项`, "ADAPTER_OUTDATED", true);
    dom.click(reader);
    const tagSelector = dom.query(contract.selectors.tag_selector);
    if (!tagSelector) throw coded("创建页未找到作品标签选择器", "ADAPTER_OUTDATED", true);
    dom.click(tagSelector);
    const tagModal = await dom.waitFor(() => dom.query(contract.selectors.tag_modal));
    if (!tagModal) throw coded("作品标签弹窗未打开", "ADAPTER_OUTDATED", true);
    for (const [parent, child] of values.tags) {
      const tab = dom.action([parent], tagModal);
      if (!tab) throw coded(`创建页未找到标签分组：${parent}`, "ADAPTER_OUTDATED", true);
      dom.click(tab);
      await dom.delay(200);
      const option = dom.queryAll(contract.selectors.tag_option, tagModal)
        .find((node) => (node.textContent || "").trim() === child);
      if (!option) throw coded(`创建页未找到作品标签：${child}`, "ADAPTER_OUTDATED", true);
      dom.click(option);
      await dom.delay(200);
    }
    const tagConfirm = dom.action(contract.actions.tag_confirm, tagModal);
    if (!tagConfirm) throw coded("作品标签弹窗缺少确认按钮", "ADAPTER_OUTDATED", true);
    dom.click(tagConfirm);
    const protagonistInputs = dom.queryAll(contract.selectors.protagonist);
    for (const [index, value] of values.protagonists.slice(0, 2).entries()) {
      if (!protagonistInputs[index]) throw coded("创建页主角输入框数量不足", "ADAPTER_OUTDATED", true);
      dom.setField(protagonistInputs[index], value.slice(0, 5));
    }
    const intro = dom.query(contract.selectors.intro);
    if (!intro) throw coded("创建页未找到简介输入框", "ADAPTER_OUTDATED", true);
    dom.setField(intro, values.intro.slice(0, 500));
    let upload = document.querySelector(contract.selectors.cover_file.join(","));
    if (!upload) {
      const chooseCover = dom.action(["选择封面"]);
      if (!chooseCover) throw coded("创建页未找到选择封面入口", "ADAPTER_OUTDATED", true);
      dom.click(chooseCover);
      upload = await dom.waitFor(() => document.querySelector(contract.selectors.cover_file.join(",")));
    }
    if (!upload) throw coded("封面弹窗未生成上传控件", "ADAPTER_OUTDATED", true);
    const bytes = Uint8Array.from(atob(payload.cover_file.data_base64), (value) => value.charCodeAt(0));
    const file = new File([bytes], payload.cover_file.name, { type: payload.cover_file.mime_type });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    upload.files = transfer.files;
    upload.dispatchEvent(new Event("change", { bubbles: true }));
    const coverModal = await dom.waitFor(() => document.querySelector(".cover-modal"));
    const coverConfirm = coverModal && await dom.waitFor(() => {
      const button = dom.action(["确定"], coverModal);
      return button && !button.disabled && button.getAttribute("aria-disabled") !== "true" ? button : null;
    });
    if (!coverConfirm) throw coded("封面上传后未出现可用的确定按钮", "WAITING_USER", true);
    dom.click(coverConfirm);
    await dom.delay(400);

    for (const activity of document.querySelectorAll(".essay-activity-item")) {
      if (!activity.querySelector(".essay-activity-item-radio-icon-selected")) continue;
      const radio = activity.querySelector(".essay-activity-item-radio") || activity;
      dom.click(radio);
      await dom.delay(200);
      if (activity.querySelector(".essay-activity-item-radio-icon-selected"))
        throw coded("无法取消番茄默认勾选的征文活动", "WAITING_USER", true);
    }

    const submit = await dom.waitFor(() => dom.action(contract.actions.create_confirm, document, { exact: false }), 10000);
    if (!submit || submit.disabled || submit.getAttribute("aria-disabled") === "true")
      throw coded("番茄建书页资料尚未补全或创建按钮不可用", "WAITING_USER", true);
    let createNetworkResult = null;
    const createListener = (event) => {
      if (event.detail?.kind === "create_book") createNetworkResult = event.detail;
    };
    window.addEventListener("maliang-publish-network", createListener);
    dom.click(submit);
    const outcome = await dom.waitFor(() => {
      const bookId = location.href.match(/chapter-manage\/(\d+)/)?.[1]
        || dom.query(contract.selectors.book_links)?.href?.match(/chapter-manage\/(\d+)/)?.[1];
      if (bookId) return { bookId };
      if (createNetworkResult) return { network: createNetworkResult };
      return null;
    }, contract.timeouts_ms.book_created);
    window.removeEventListener("maliang-publish-network", createListener);
    if (outcome?.network && !outcome.network.ok)
      throw new Error(outcome.network.message || `番茄建书接口失败 ${outcome.network.code || outcome.network.status}`);
    const bookId = outcome?.bookId || outcome?.network?.platform_book_id;
    if (!bookId) throw coded("创建请求结果不明确，需回到作品管理页确认", "AMBIGUOUS_RESULT");
    return { platform_book_id: bookId, book_name: payload.book_name };
  }

  async function fillChapter(payload) {
    const title = await dom.waitFor(() => dom.query(contract.selectors.chapter_title));
    const content = await dom.waitFor(() => dom.query(contract.selectors.chapter_content));
    if (!title || !content) throw coded("番茄发布页结构已变化，找不到标题或正文编辑器", "ADAPTER_OUTDATED", true);
    const normalizedTitle = String(payload.title || "").replace(/^第\s*\d+\s*章[：:\s-]*/, "").trim();
    const titleLength = [...normalizedTitle].length;
    if (titleLength < 5 || titleLength > 30)
      throw coded("番茄章节标题需为 5 至 30 个字", "INVALID_PAYLOAD");
    const number = dom.query(contract.selectors.chapter_number);
    if (number) dom.setField(number, payload.chapter_no);
    dom.setField(title, normalizedTitle);
    dom.setEditor(content, payload.body || "");
    const editorReady = await dom.waitFor(() => {
      const text = dom.bodyText();
      const count = text.match(/正文字数\s*(\d+)/);
      return title.value === normalizedTitle
        && Number(count?.[1] || 0) > 0;
    }, contract.timeouts_ms.element);
    if (!editorReady) throw coded("番茄编辑器未确认标题或正文字数", "ADAPTER_OUTDATED", true);
  }

  async function waitPublishSettings() {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const next = dom.action(contract.actions.next);
      if (!next) throw coded("番茄发布页结构已变化，找不到下一步按钮", "ADAPTER_OUTDATED", true);
      dom.click(next);
      const ready = await dom.waitFor(() => {
        const text = dom.bodyText();
        return /是否使用\s*AI|错别字未修改|内容检测方式|内容风险检测|确认发布/.test(text);
      }, 10000, 250);
      if (ready) return;
    }
    throw coded("点击下一步后未进入发布设置", "ADAPTER_OUTDATED", true);
  }

  async function settlePublishDialogs() {
    const end = Date.now() + 60000;
    while (Date.now() < end) {
      const text = dom.bodyText();
      if (text.includes("错别字未修改")) {
        const submit = dom.action(contract.actions.submit_typo);
        if (!submit) throw coded("错别字提示缺少“提交”操作", "ADAPTER_OUTDATED", true);
        dom.click(submit);
      } else if (text.includes("请选择内容检测方式")) {
        const basic = dom.action(contract.actions.basic_detection, document, { exact: false });
        if (!basic) throw coded("内容检测提示缺少“仅基础检测”操作", "ADAPTER_OUTDATED", true);
        dom.click(basic);
      } else if (text.includes("内容风险检测")) {
        const cancel = dom.action(contract.actions.cancel_risk);
        if (!cancel) throw coded("风险检测提示缺少安全取消操作", "ADAPTER_OUTDATED", true);
        dom.click(cancel);
      } else if (/是否使用\s*AI|确认发布/.test(text)) {
        return;
      } else {
        await dom.delay(250);
        continue;
      }
      await dom.delay(300);
    }
    throw coded("等待发布设置超时", "ADAPTER_OUTDATED", true);
  }

  function selectAiYes(root = document) {
    const yes = [...root.querySelectorAll('label, [role="radio"]')].filter(dom.visible).find((node) => {
      if ((node.textContent || "").trim() !== "是") return false;
      const group = node.closest('[role="radiogroup"], .arco-radio-group') || node.parentElement;
      return [...group.querySelectorAll('label, [role="radio"]')]
        .some((option) => (option.textContent || "").trim() === "否");
    });
    if (!yes) throw coded("发布设置未提供可核验的“使用 AI：是”", "ADAPTER_OUTDATED", true);
    dom.click(yes);
    const node = yes.closest('[role="radio"],[role="checkbox"],label,button') || yes;
    const input = node.matches("input") ? node : node.querySelector("input");
    if (!(input?.checked || node.getAttribute("aria-checked") === "true" || node.getAttribute("aria-pressed") === "true"
      || /selected|checked|active/.test(String(node.className))))
      throw coded("无法核验“使用 AI：是”已选中", "ADAPTER_OUTDATED", true);
  }

  async function configureSchedule(root, scheduledAt) {
    if (!scheduledAt) return;
    let date = dom.query(contract.selectors.date, root);
    let time = dom.query(contract.selectors.time, root);
    if (!date || !time) {
      const labels = [...root.querySelectorAll("*")].filter(dom.visible)
        .filter((node) => (node.innerText || "").trim() === "定时发布");
      let switched = false;
      for (const label of labels) {
        let row = label;
        for (let depth = 0; row && depth < 6; depth += 1, row = row.parentElement) {
          const controls = [...row.querySelectorAll(
            '[role="switch"], button, input[type="checkbox"], [class*="switch"], [class*="Switch"]'
          )].filter(dom.visible);
          const target = controls.find((node) => !(node.innerText || "").includes("定时发布"))
            || controls.at(-1);
          if (!target) continue;
          dom.click(target);
          switched = true;
          break;
        }
        if (switched) break;
      }
      if (!switched) throw coded("发布设置未找到定时发布开关", "ADAPTER_OUTDATED", true);
      await dom.delay(500);
      date = dom.query(contract.selectors.date, root);
      time = dom.query(contract.selectors.time, root);
    }
    const value = new Date(scheduledAt);
    const pad = (number) => String(number).padStart(2, "0");
    const dateValue = `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
    const timeValue = `${pad(value.getHours())}:${pad(value.getMinutes())}`;
    if (date && time) {
      dom.setField(date, dateValue);
      dom.setField(time, timeValue);
      if (date.value !== dateValue || time.value.slice(0, 5) !== timeValue)
        throw coded("定时发布时间回读不一致", "ADAPTER_OUTDATED", true);
      return;
    }
    const combined = root.querySelector(".arco-picker input, input.arco-picker-input, input[placeholder*='时间']");
    if (!combined) throw coded("发布设置未找到日期和时间输入框", "ADAPTER_OUTDATED", true);
    dom.setField(combined, `${dateValue} ${timeValue}`);
  }

  async function publishChapter(payload) {
    await fillChapter(payload);
    let networkResult = null;
    const listener = (event) => { networkResult = event.detail; };
    window.addEventListener("maliang-publish-network", listener);
    try {
      await waitPublishSettings();
      await settlePublishDialogs();
      selectAiYes(document);
      if (payload.scheduled_at) {
        await configureSchedule(document, payload.scheduled_at);
        selectAiYes(document);
      }
      const confirm = [...document.querySelectorAll('button,[role="button"]')].filter(dom.visible)
        .filter((node) => (node.innerText || "").trim() === "确认发布").at(-1)
        || dom.action(contract.actions.confirm_publish);
      if (!confirm) throw coded("发布设置未找到确认发布按钮", "ADAPTER_OUTDATED", true);
      dom.click(confirm);
      const end = Date.now() + contract.timeouts_ms.publish_result;
      while (Date.now() < end) {
        const risk = riskReason();
        if (risk) throw coded(risk, "WAITING_USER");
        if (networkResult) {
          if (!networkResult.ok) throw new Error(networkResult.message || `番茄发布接口失败 ${networkResult.code || networkResult.status}`);
          return networkResult;
        }
        const text = dom.bodyText();
        if (includesAny(text, contract.signals.publish_success)
          || !text.includes("确认发布") && !text.includes("发布设置"))
          return { ok: true, reconciled_from_page: true };
        await dom.delay(500);
      }
      throw coded("未观察到平台成功证据，正在回读番茄章节列表", "AMBIGUOUS_RESULT");
    } finally {
      window.removeEventListener("maliang-publish-network", listener);
    }
  }

  function platformVerified(status) {
    const value = String(status ?? "").trim().toLowerCase();
    return ["published", "scheduled", "reviewing", "审核中", "已发布", "定时发布", "待发布"].includes(value)
      || /已发布|审核中|定时|待发布/.test(value) || [1, 2, 3, 4].includes(Number(status));
  }

  async function execute(job) {
    const payload = job.payload || {};
    const identity = await settledIdentity(payload);
    const risk = riskReason();
    // Session probes must report unauthenticated instead of becoming a stuck
    // waiting-user job. Write operations still stop immediately.
    if (risk && job.operation !== "CHECK_SESSION") throw coded(risk, "WAITING_USER");
    if (identityMismatch(payload, identity)) return { identity_mismatch: true, ...identity };
    switch (job.operation) {
      case "CHECK_SESSION": return identity;
      case "LIST_BOOKS": {
        await dom.waitFor(() => dom.query(contract.selectors.book_links)
          || /暂无作品|还没有作品|暂无小说/.test(dom.bodyText()), contract.timeouts_ms.element);
        return { books: listBooks(), identity: currentIdentity(), diagnostics: dom.diagnostics() };
      }
      case "CREATE_BOOK": return createBook(payload);
      case "LIST_CHAPTERS": {
        const listed = await listChapters();
        return { chapters: listed.chapters, chapters_complete: listed.complete };
      }
      case "PUBLISH_CHAPTER":
      case "OVERWRITE_CHAPTER": return publishChapter(payload);
      case "VERIFY_CHAPTER": {
        const listed = await listChapters();
        const found = listed.chapters.find((chapter) => chapter.number === Number(payload.chapter_no));
        if (!found) throw new Error("平台尚未找到该章节，稍后继续验证");
        return { ...found, platform_verified: platformVerified(found.status) };
      }
      case "CANCEL_BATCH": return { cancelled: true };
      default: throw new Error(`不支持的任务类型：${job.operation}`);
    }
  }

  async function reconcileAmbiguous(job) {
    if (job.operation === "CREATE_BOOK") {
      const found = listBooks().filter((book) => book.book_name === job.payload?.book_name);
      return found.length === 1 ? { ...found[0], ambiguous_reconciled: true } : null;
    }
    const listed = await listChapters();
    const found = listed.chapters.find((chapter) => chapter.number === Number(job.payload?.chapter_no));
    return found ? { ...found, ambiguous_reconciled: true, platform_verified: platformVerified(found.status) } : null;
  }

  globalThis.MaliangFanqieAdapter = { execute, reconcileAmbiguous, parseChapterRows, inferStatus };
})();
