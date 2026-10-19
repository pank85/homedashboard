(function () {
  var current = 0;

  function pageSize(size) {
    if (typeof size === "number" && isFinite(size) && size >= 1 && Math.floor(size) === size) {
      return size;
    }
    return 5;
  }

  function pageContainers(rows, page, size) {
    var list = Array.isArray(rows) ? rows : [];
    var resolved = pageSize(size);
    var total = list.length;
    var pages = total === 0 ? 1 : Math.ceil(total / resolved);
    var index = 0;
    if (typeof page === "number" && isFinite(page)) {
      index = Math.floor(page);
    }
    if (index < 0) {
      index = 0;
    }
    if (index > pages - 1) {
      index = pages - 1;
    }
    var start = index * resolved;
    return {
      rows: list.slice(start, start + resolved),
      page: index,
      pages: pages,
      total: total,
      size: resolved,
    };
  }

  function containerPage() {
    return current;
  }

  function setContainerPage(page) {
    if (typeof page !== "number" || !isFinite(page) || page < 0 || Math.floor(page) !== page) {
      return;
    }
    current = page;
  }

  function resetContainerPage() {
    current = 0;
  }

  globalThis.pageContainers = pageContainers;
  globalThis.containerPage = containerPage;
  globalThis.setContainerPage = setContainerPage;
  globalThis.resetContainerPage = resetContainerPage;
  globalThis.CONTAINER_PAGE_SIZE = 5;
})();
