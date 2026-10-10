/* RestStop UK sitewide GA4 loader for static SEO pages */
(function () {
  'use strict';

  var MEASUREMENT_ID = 'G-QKVW0EETP0';
  var CONSENT_KEY = 'rsuk_analytics_consent';

  function getConsent() {
    try { return localStorage.getItem(CONSENT_KEY); } catch (_) { return null; }
  }

  function setConsent(value) {
    try { localStorage.setItem(CONSENT_KEY, value); } catch (_) {}
    if (value === 'granted') loadGA();
    removeBanner();
  }

  function loadGA() {
    if (window.__rsukGaLoaded) return;
    window.__rsukGaLoaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function(){ window.dataLayer.push(arguments); };

    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(MEASUREMENT_ID);
    document.head.appendChild(s);

    window.gtag('js', new Date());
    window.gtag('config', MEASUREMENT_ID, {
      send_page_view: true,
      page_location: window.location.href,
      page_path: window.location.pathname + window.location.search,
      page_title: document.title
    });
  }

  function removeBanner() {
    var el = document.getElementById('rsuk-analytics-consent');
    if (el) el.remove();
  }

  function showBanner() {
    if (document.getElementById('rsuk-analytics-consent')) return;

    var wrap = document.createElement('div');
    wrap.id = 'rsuk-analytics-consent';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-label', 'Analytics preferences');
    wrap.innerHTML =
      '<div class="rsuk-consent-card">' +
        '<div class="rsuk-consent-copy">' +
          '<strong>Help us improve RestStop UK</strong>' +
          '<span>Allow anonymous analytics so we can understand which road and stop pages are useful. You can continue without accepting.</span>' +
        '</div>' +
        '<div class="rsuk-consent-actions">' +
          '<button type="button" data-rsuk-consent="denied">No thanks</button>' +
          '<button type="button" class="rsuk-accept" data-rsuk-consent="granted">Allow analytics</button>' +
        '</div>' +
      '</div>';

    var style = document.createElement('style');
    style.id = 'rsuk-analytics-consent-style';
    style.textContent =
      '#rsuk-analytics-consent{position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483647;font-family:system-ui,-apple-system,Segoe UI,sans-serif}' +
      '.rsuk-consent-card{max-width:760px;margin:0 auto;background:#fff;color:#111916;border:1px solid #d9dedb;border-radius:16px;padding:16px;box-shadow:0 12px 35px rgba(0,0,0,.18);display:flex;gap:16px;align-items:center;justify-content:space-between}' +
      '.rsuk-consent-copy{display:grid;gap:5px;line-height:1.35}.rsuk-consent-copy strong{font-size:18px}.rsuk-consent-copy span{font-size:14px;color:#58645f;max-width:56ch}' +
      '.rsuk-consent-actions{display:flex;gap:8px;flex-wrap:wrap;flex:none}.rsuk-consent-actions button{min-height:44px;padding:0 14px;border-radius:10px;border:1px solid #b9c2bc;background:#fff;color:#111916;font-weight:700;cursor:pointer}' +
      '.rsuk-consent-actions .rsuk-accept{background:#087943;border-color:#087943;color:#fff}' +
      '@media(max-width:640px){.rsuk-consent-card{align-items:stretch;flex-direction:column}.rsuk-consent-actions{display:grid;grid-template-columns:1fr 1fr}.rsuk-consent-actions button{width:100%}}';

    document.head.appendChild(style);
    document.body.appendChild(wrap);

    wrap.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-rsuk-consent]');
      if (!btn) return;
      setConsent(btn.getAttribute('data-rsuk-consent'));
    });
  }

  function init() {
    var consent = getConsent();
    if (consent === 'granted') {
      loadGA();
    } else if (consent !== 'denied') {
      showBanner();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();