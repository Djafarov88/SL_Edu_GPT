// Sportleader Academy — Main JS

document.addEventListener('DOMContentLoaded', function () {
  // Initialize Bootstrap tooltips
  const tooltipEls = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipEls.forEach(el => new bootstrap.Tooltip(el));

  // Auto-dismiss alerts after 5s
  document.querySelectorAll('.alert.alert-dismissible').forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    }, 5000);
  });

  // Smooth progress bar animation on load
  document.querySelectorAll('.progress-bar').forEach(function (bar) {
    const target = bar.style.width;
    bar.style.width = '0%';
    setTimeout(function () {
      bar.style.transition = 'width .8s ease';
      bar.style.width = target;
    }, 200);
  });
});
