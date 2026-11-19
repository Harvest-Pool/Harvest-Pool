function setupMenu(trigger, navigationId, breakpoint) {
  const menu = document.querySelector(trigger);
  const navigation = document.getElementById(navigationId);
  if (!menu || !navigation) return;
  const compact = window.matchMedia(breakpoint);

  function setMenu(open) {
    navigation.hidden = compact.matches && !open;
    menu.setAttribute('aria-expanded', String(compact.matches && open));
  }

  function resetMenu() {
    menu.hidden = !compact.matches;
    setMenu(false);
  }

  menu.addEventListener('click', () => setMenu(navigation.hidden));
  compact.addEventListener('change', resetMenu);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
      setMenu(false);
      menu.focus();
    }
  });
  navigation.addEventListener('click', event => {
    if (compact.matches && event.target.closest('a')?.hash) {
      setMenu(false);
      menu.focus({preventScroll: true});
    }
  });
  resetMenu();
}

setupMenu('.site-header .site-menu-toggle', 'site-navigation', '(max-width: 1120px)');
setupMenu('.workspace-menu-toggle', 'workspace-navigation', '(max-width: 950px)');

document.querySelectorAll('.pilot-visual').forEach(visual => {
  const controls = visual.querySelector('.pilot-controls');
  const comparison = visual.querySelector('.pilot-comparison');
  const buttons = Array.from(controls.querySelectorAll('button'));
  controls.hidden = false;
  buttons.forEach(button => button.addEventListener('click', () => {
    const mode = button.dataset.preview;
    comparison.dataset.preview = mode;
    comparison.querySelector('.pilot-before').hidden = mode === 'after';
    comparison.querySelector('.pilot-after').hidden = mode === 'before';
    buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  }));
});
