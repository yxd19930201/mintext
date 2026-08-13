(() => {
  "use strict";
  const MATCH = /\/api\/author\/(?:book\/create|publish_article|chapter\/(?:publish|update)|article\/(?:publish|update))/;
  const emit = (detail) => window.dispatchEvent(new CustomEvent("maliang-publish-network", { detail }));
  const kind = (url) => url.includes("/book/create") ? "create_book" : "publish_chapter";
  const detailFrom = (url, response, body) => ({
    kind: kind(url),
    ok: response.ok && Number(body?.code ?? 0) === 0,
    status: response.status,
    code: body?.code,
    message: body?.message || body?.msg || "",
    platform_book_id: body?.data?.book_id || body?.data?.bookId || body?.data?.book?.book_id || null,
    platform_chapter_id: body?.data?.article_id || body?.data?.chapter_id || null,
  });

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    const url = String(args[0]?.url || args[0] || "");
    if (MATCH.test(url)) {
      response.clone().json().then((body) => emit(detailFrom(url, response, body)))
        .catch(() => emit({ kind: kind(url), ok: response.ok, status: response.status }));
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__maliangPublishUrl = String(url || "");
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    if (MATCH.test(this.__maliangPublishUrl || "")) {
      this.addEventListener("loadend", () => {
        let body = null;
        try { body = JSON.parse(this.responseText || "{}"); } catch (_) {}
        emit(detailFrom(this.__maliangPublishUrl, {
          ok: this.status >= 200 && this.status < 300, status: this.status,
        }, body));
      }, { once: true });
    }
    return originalSend.apply(this, args);
  };
})();
