import assert from "node:assert/strict";
import { answerFingerprint, classifyAuthenticationState, pageLikelyContainsPrompt, selectLongestResponseCandidate } from "./browser-adapter.js";

const shared = "统一小说连续性规则".repeat(80);
const draft = `${shared}\n生成完整小说正文，只输出正文并保留自然段换行。`;
const audit = `${shared}\n只输出审核 JSON，不得返回或复述小说正文。`;
const pageWithDraft = `用户：${draft}\n助手：正文内容`;

assert.equal(pageLikelyContainsPrompt(pageWithDraft, draft), true);
assert.equal(pageLikelyContainsPrompt(pageWithDraft, audit), false);

// DOM selector order and de-duplication can change between renders.  A count
// based slice can therefore return an old answer.  Fingerprint exclusion keeps
// only the answer created after this request.
const oldAnswer = '{"state_ledger":{"current_chapter":74}}';
const newAnswer = '{"content":"new chapter prose"}';
const baseline = new Set([answerFingerprint(oldAnswer)]);
const reordered = [newAnswer, oldAnswer].filter(
  (candidate) => !baseline.has(answerFingerprint(candidate)),
);
assert.equal(selectLongestResponseCandidate(reordered), newAnswer);

// The prompt itself contains the output envelope example. It must never be
// eligible as a model answer when the provider reports a network error.
assert.equal(pageLikelyContainsPrompt(`${draft}\n${oldAnswer}`, draft), true);

assert.equal(
  classifyAuthenticationState(
    "DeepSeek", "DeepSeek", "由于违反用户使用规范，你的账号已被禁言至明日", "https://chat.deepseek.com/",
    false, false,
  )?.state,
  "verification_required",
);
