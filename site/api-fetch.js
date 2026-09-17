(() => {
  const nativeFetch = window.fetch.bind(window);
  const API_ORIGIN = "https://futureview.rueijrwu.workers.dev";

  window.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input?.url;
    if (typeof url === "string" && url.startsWith(`${API_ORIGIN}/api/`)) {
      return nativeFetch(input, { ...init, cache: "no-store" });
    }
    return nativeFetch(input, init);
  };
})();
