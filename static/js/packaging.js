(() => {
  const form = document.getElementById('quote-form');
  const {listing_id, quantity_kg, service, labelled_units, new_design} = form.elements;
  const output = document.getElementById('quote-estimate');
  const currency = new Intl.NumberFormat('en-ZA', {style: 'currency', currency: 'ZAR'});

  function updateEstimate() {
    const branding = service.value !== 'packaging';
    const packing = service.value !== 'branding';
    quantity_kg.max = Math.min(1e6, Number(listing_id.selectedOptions[0].dataset.stock));
    labelled_units.disabled = new_design.disabled = !branding;
    labelled_units.required = branding;
    labelled_units.min = branding ? 1 : 0;
    const packagingCost = packing ? Number(quantity_kg.value) * Number(form.dataset.pack) : 0;
    const brandingCost = branding ? Number(labelled_units.value) * Number(form.dataset.label) : 0;
    const artworkCost = branding && new_design.checked ? Number(form.dataset.art) : 0;
    output.value = currency.format(packagingCost + brandingCost + artworkCost);
  }

  form.addEventListener('input', updateEstimate);
  form.addEventListener('change', updateEstimate);
  updateEstimate();
})();
