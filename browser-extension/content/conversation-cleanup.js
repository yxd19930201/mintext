(() => {
  "use strict";

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && box.width > 0 && box.height > 0;
  }

  function parseConversationUrl(value, definition) {
    try {
      const url = new URL(value, location.href);
      if (!definition.hosts.includes(url.hostname)) return null;
      if (!definition.conversationPathPattern?.test(url.pathname)) return null;
      return { key: url.pathname, href: url.href };
    } catch (_) {
      return null;
    }
  }

  function normalizedAnchor(anchor, definition) {
    const target = parseConversationUrl(anchor.getAttribute("href") || anchor.href, definition);
    return target ? { ...target, title: (anchor.innerText || anchor.textContent || "").trim() } : null;
  }

  function conversationAnchors(definition) {
    const selector = (definition.conversationLinkSelectors || []).join(",");
    if (!selector) return [];
    return [...document.querySelectorAll(selector)]
      .map((anchor) => ({ anchor, conversation: normalizedAnchor(anchor, definition) }))
      .filter((item) => item.conversation);
  }

  async function ensureHistoryVisible(definition) {
    if (conversationAnchors(definition).length) return;
    for (const selector of definition.openSidebarSelectors || []) {
      const button = [...document.querySelectorAll(selector)].find(visible);
      if (button) {
        button.click();
        break;
      }
    }
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline && conversationAnchors(definition).length === 0) await sleep(150);
  }

  function historyScroller(definition) {
    const first = conversationAnchors(definition)[0]?.anchor;
    if (!first) return null;
    let current = first.parentElement;
    while (current && current !== document.body) {
      const style = getComputedStyle(current);
      if (current.scrollHeight > current.clientHeight + 40 && /auto|scroll/.test(style.overflowY)) return current;
      current = current.parentElement;
    }
    return null;
  }

  function findConversationAnchor(definition, key) {
    return conversationAnchors(definition).find((item) => item.conversation.key === key)?.anchor || null;
  }

  async function revealConversation(definition, key) {
    await ensureHistoryVisible(definition);
    let anchor = findConversationAnchor(definition, key);
    if (anchor) return anchor;
    const scroller = historyScroller(definition);
    if (!scroller) return null;
    scroller.scrollTop = 0;
    await sleep(100);
    for (let step = 0; step < 240; step += 1) {
      anchor = findConversationAnchor(definition, key);
      if (anchor) return anchor;
      const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      if (scroller.scrollTop >= maxScroll - 4) break;
      scroller.scrollTop = Math.min(maxScroll, scroller.scrollTop + Math.max(240, scroller.clientHeight * 0.8));
      await sleep(100);
    }
    return findConversationAnchor(definition, key);
  }

  function hover(element) {
    for (const type of ["pointerover", "mouseover", "mouseenter"]) {
      element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
  }

  function firstVisibleWithin(root, selectors) {
    for (const selector of selectors || []) {
      for (const element of root.querySelectorAll(selector)) {
        if (visible(element)) return element;
      }
    }
    return null;
  }

  async function conversationMenu(anchor, definition, target) {
    const linkSelector = (definition.conversationLinkSelectors || []).join(",");
    let row = anchor.parentElement;
    for (let depth = 0; row && depth < 8; depth += 1, row = row.parentElement) {
      const rowConversations = linkSelector ? [...row.querySelectorAll(linkSelector)]
        .map((item) => normalizedAnchor(item, definition)).filter(Boolean) : [];
      if (rowConversations.length !== 1 || rowConversations[0].key !== target.key) continue;
      hover(row);
      await sleep(80);
      const preferred = firstVisibleWithin(row, definition.conversationMenuSelectors);
      if (preferred) return preferred;
      const fallback = [...row.querySelectorAll('button,[role="button"]')].filter(visible).at(-1);
      if (fallback && !fallback.contains(anchor) && !anchor.contains(fallback)) return fallback;
    }
    return null;
  }

  function exactTextAction(root, texts, selector) {
    const allowed = new Set((texts || []).map((value) => value.trim().toLowerCase()));
    return [...root.querySelectorAll(selector)].find((element) => {
      const text = (element.innerText || element.textContent || "").trim().toLowerCase();
      return visible(element) && allowed.has(text);
    }) || null;
  }

  async function waitForAction(texts, selector, timeoutMs = 2_500, root = document) {
    const deadline = Date.now() + timeoutMs;
    do {
      const action = exactTextAction(root, texts, selector);
      if (action) return action;
      await sleep(100);
    } while (Date.now() < deadline);
    return null;
  }

  function visibleDeleteDialog() {
    return [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')].find(visible) || null;
  }

  async function waitForDeleteTransition(definition, key, timeoutMs = 3_000) {
    const deadline = Date.now() + timeoutMs;
    do {
      if (!findConversationAnchor(definition, key)) return { gone: true, dialog: null };
      const dialog = visibleDeleteDialog();
      if (dialog) return { gone: false, dialog };
      await sleep(100);
    } while (Date.now() < deadline);
    return { gone: false, dialog: null };
  }

  async function waitUntilGone(definition, key, timeoutMs = 4_000) {
    const deadline = Date.now() + timeoutMs;
    do {
      if (!findConversationAnchor(definition, key)) return true;
      await sleep(120);
    } while (Date.now() < deadline);
    return false;
  }

  async function deleteExactConversation(definition, target) {
    const anchor = await revealConversation(definition, target.key);
    if (!anchor) throw new Error("找不到青玉本次使用的会话，已保留该会话");
    anchor.scrollIntoView({ block: "nearest" });
    hover(anchor);
    const menu = await conversationMenu(anchor, definition, target);
    if (!menu) throw new Error("无法确认本次会话的操作菜单，已保留该会话");
    menu.click();
    const deleteAction = await waitForAction(
      definition.deleteActionTexts,
      '[role="menuitem"],[data-radix-collection-item],button,[role="button"]',
    );
    if (!deleteAction) throw new Error("无法确认本次会话的删除命令，已保留该会话");
    deleteAction.click();
    const transition = await waitForDeleteTransition(definition, target.key);
    if (transition.gone) return;
    if (transition.dialog) {
      const confirm = await waitForAction(definition.deleteConfirmTexts, 'button,[role="button"]', 2_500, transition.dialog);
      if (!confirm) throw new Error("无法确认本次会话的删除按钮，已停止操作");
      confirm.click();
    } else {
      throw new Error("删除命令没有出现确认弹窗，已保留本次会话");
    }
    if (!await waitUntilGone(definition, target.key)) {
      throw new Error("删除后仍检测到本次会话，已停止操作");
    }
  }

  let running = null;
  function remove(definition, conversationUrl, options = {}) {
    if (running) return running;
    const report = typeof options.report === "function" ? options.report : async () => {};
    running = (async () => {
      const target = parseConversationUrl(conversationUrl, definition);
      if (!target) {
        const state = { status: "preserved", deleted: false, reason: "no_unique_conversation_url" };
        await report(state);
        return state;
      }
      await report({ status: "deleting", deleted: false, conversation_key: target.key });
      try {
        await deleteExactConversation(definition, target);
      } catch (error) {
        await report({ status: "preserved", deleted: false, conversation_key: target.key, error: error.message });
        throw error;
      }
      const state = { status: "deleted", deleted: true, conversation_key: target.key };
      await report(state);
      return state;
    })().finally(() => { running = null; });
    return running;
  }

  globalThis.MaliangConversationCleanup = Object.freeze({ parseConversationUrl, remove });
})();
