// Local demonstration: cost inputs only change an estimate, not an agreed price.
document.querySelectorAll('.estimate-form').forEach(form => {
  const gross = Number(form.dataset.gross);
  const output = form.querySelector('.net-preview');
  const update = () => {
    const transport = Number(form.querySelector('[name="transport_cost"]').value || 0);
    const packaging = Number(form.querySelector('[name="packaging_cost"]').value || 0);
    const net = gross - transport - packaging;
    output.textContent = Number.isFinite(net) ?
      `Estimated net: R${net.toFixed(2)} (before other costs)` : 'Enter valid costs';
  };
  form.addEventListener('input', update);
  update();
});
