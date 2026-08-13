(() => {
  "use strict";

  const contract = globalThis.MaliangFanqieContract;
  if (!contract) throw new Error("Maliang Fanqie adapter contract was not loaded");

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const visible = (element) => {
    if (!element) return false;
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && box.width > 1 && box.height > 1;
  };
  const query = (selectors, root = document) => {
    for (const selector of selectors || []) {
      const value = [...root.querySelectorAll(selector)].find(visible);
      if (value) return value;
    }
    return null;
  };
  const queryAll = (selectors, root = document) => {
    const seen = new Set();
    return (selectors || []).flatMap((selector) => [...root.querySelectorAll(selector)])
      .filter((node) => visible(node) && !seen.has(node) && seen.add(node));
  };
  const waitFor = async (test, timeout = contract.timeouts_ms.element, interval = contract.timeouts_ms.poll) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const value = test();
      if (value) return value;
      await delay(interval);
    }
    return null;
  };
  const textMatch = (node, labels, { exact = true } = {}) => {
    const text = (node.textContent || "").trim().replace(/\s+/g, " ");
    return labels.some((label) => exact ? text === label : text.includes(label));
  };
  const action = (labels, root = document, options = {}) => {
    const nodes = root.querySelectorAll('button, a, label, [role="button"], [role="radio"], [role="option"], [role="tab"], .write-button, .write-button-dropdown-item-title, .category-choose-item-title');
    return [...nodes].filter(visible).find((node) => textMatch(node, labels, options)) || null;
  };
  const click = (element) => {
    if (!visible(element)) throw new Error("目标控件不可见");
    element.scrollIntoView({ block: "center", behavior: "instant" });
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    element.click();
  };
  const hover = (element) => {
    if (!visible(element)) throw new Error("目标控件不可见");
    element.scrollIntoView({ block: "center", behavior: "instant" });
    for (const type of ["pointerover", "mouseover", "mouseenter"])
      element.dispatchEvent(new MouseEvent(type, { bubbles: true, view: window }));
  };
  const setField = (element, value) => {
    element.focus();
    const text = String(value);
    if (typeof element.select === "function") element.select();
    if (document.execCommand("insertText", false, text)) {
      element.dispatchEvent(new Event("change", { bubbles: true }));
      element.dispatchEvent(new Event("blur", { bubbles: true }));
      if (typeof element.blur === "function") element.blur();
      if (String(element.value).trim() !== text.trim()) throw new Error("输入内容回读不一致");
      return;
    }
    const prototype = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (setter) setter.call(element, text);
    else element.value = text;
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true }));
    if (typeof element.blur === "function") element.blur();
    if (String(element.value).trim() !== text.trim()) throw new Error("输入内容回读不一致");
  };
  const setEditor = (element, value) => {
    if (!element.matches('[contenteditable="true"], .ProseMirror, .ql-editor')) return setField(element, value);
    element.focus();
    document.execCommand("selectAll", false);
    if (document.execCommand("insertText", false, String(value))) return;
    element.innerHTML = "";
    for (const paragraph of String(value).split(/\n+/).map((item) => item.trim()).filter(Boolean)) {
      const node = document.createElement("p");
      node.textContent = paragraph;
      element.appendChild(node);
    }
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
  };
  const bodyText = () => document.body?.innerText || "";
  const diagnostics = () => ({
    contract_version: contract.version,
    url: location.href,
    title: document.title,
    actions: [...document.querySelectorAll('button, a, label, [role="button"], [role="radio"], [role="option"]')]
      .filter(visible).map((node) => ({
        tag: node.tagName,
        text: (node.textContent || "").trim().replace(/\s+/g, " ").slice(0, 120),
        href: node.href || null,
        disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
      })).slice(0, 120),
    inputs: [...document.querySelectorAll("input, textarea")].filter(visible).map((input) => ({
      tag: input.tagName, type: input.type || null, name: input.name || null,
      placeholder: input.placeholder || null, checked: Boolean(input.checked),
    })).slice(0, 100),
  });

  globalThis.MaliangDomDriver = {
    contract, delay, visible, query, queryAll, waitFor, action, click, hover, setField, setEditor, bodyText, diagnostics,
  };
})();
