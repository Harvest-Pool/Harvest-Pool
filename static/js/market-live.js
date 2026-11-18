(() => {
  const section = document.getElementById('market-results');
  const form = section.querySelector('form');
  const results = document.getElementById('market-listings');
  const feedback = document.getElementById('market-feedback');
  const count = document.getElementById('mp-count');
  let timer;
  let pending;

  function filterUrl() {
    const url = new URL(form.action);
    for (const [name, value] of new FormData(form)) {
      const filter = value.trim();
      if (filter && !(name === 'sort' && filter === 'newest')) url.searchParams.set(name, filter);
    }
    return url;
  }

  async function update(url, historyMode) {
    clearTimeout(timer);
    pending?.abort();
    const controller = new AbortController();
    pending = controller;
    results.setAttribute('aria-busy', 'true');
    feedback.textContent = 'Finding produce?';
    try {
      const response = await fetch(url, {signal: controller.signal});
      if (!response.ok) throw new Error('Marketplace request failed');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = page.getElementById('market-listings');
      const nextCount = page.getElementById('mp-count');
      const nextForm = page.querySelector('.mp-toolbar');
      if (!next || !nextCount || !nextForm) throw new Error('Missing marketplace results');
      if (controller.signal.aborted) return;
      results.replaceChildren(...next.childNodes);
      count.textContent = nextCount.textContent;
      feedback.textContent = count.textContent === '1' ? '1 listing on this page' :
        count.textContent + ' listings on this page';
      if (historyMode !== 'replaceState') {
        for (const field of nextForm.elements) {
          if (field.name && form.elements.namedItem(field.name)) {
            form.elements.namedItem(field.name).value = field.value;
          }
        }
      }
      if (url.href !== window.location.href) history[historyMode](null, '', url);
    } catch (error) {
      if (!controller.signal.aborted) feedback.textContent = 'Could not update listings. Use Apply filters to retry.';
    } finally {
      if (pending === controller) {
        pending = undefined;
        results.removeAttribute('aria-busy');
      }
    }
  }

  form.addEventListener('submit', event => {
    if (feedback.textContent.startsWith('Could not')) return;
    event.preventDefault();
    update(filterUrl(), 'pushState');
  });
  form.elements.q.addEventListener('input', event => {
    clearTimeout(timer);
    pending?.abort();
    if (!event.isComposing) timer = setTimeout(() => update(filterUrl(), 'replaceState'), 275);
  });
  form.addEventListener('change', event => {
    if (event.target.matches('select')) update(filterUrl(), 'replaceState');
  });
  section.addEventListener('click', event => {
    const link = event.target.closest('[data-market-clear], .pilot-pagination a');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey ||
        event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (link.hasAttribute('data-market-clear')) {
      form.elements.q.value = '';
      form.elements.crop.value = '';
      form.elements.sort.value = 'newest';
    } else {
      form.elements.q.focus({preventScroll: true});
    }
    update(new URL(link.href), 'pushState');
  });
  window.addEventListener('popstate', () => window.location.reload());
})();
