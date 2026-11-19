(() => {
  const form = document.querySelector('[data-sign-in]');
  if (!form) return;
  const fields = [form.elements.email, form.elements.password];

  // Lock empty inputs until the person chooses to enter credentials.
  function clearCredentials() {
    for (const field of fields) {
      field.value = '';
      field.readOnly = true;
    }
  }

  for (const field of fields) {
    const unlock = () => { field.readOnly = false; };
    field.addEventListener('pointerdown', unlock);
    field.addEventListener('focus', unlock);
    field.addEventListener('keydown', event => {
      if (event.key.length === 1 || event.key === 'Backspace') unlock();
    });
  }

  clearCredentials();
  window.addEventListener('pageshow', clearCredentials);
  window.addEventListener('pagehide', clearCredentials);
})();
