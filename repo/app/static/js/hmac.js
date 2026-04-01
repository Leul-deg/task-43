(() => {
  function buildBodyStringFromParams(params) {
    const entries = [];
    Object.keys(params || {})
      .sort()
      .forEach((key) => {
        const value = params[key];
        if (Array.isArray(value)) {
          value.forEach((val) => entries.push([key, val]));
        } else {
          entries.push([key, value]);
        }
      });
    const search = new URLSearchParams();
    entries.forEach(([key, value]) => search.append(key, value));
    return search.toString();
  }

  function buildBodyStringFromForm(form) {
    const formData = new FormData(form);
    const entries = [];
    for (const [key, value] of formData.entries()) {
      if (value instanceof File) {
        continue;
      }
      entries.push([key, value]);
    }
    entries.sort((a, b) =>
      a[0] === b[0]
        ? String(a[1]).localeCompare(String(b[1]))
        : a[0].localeCompare(b[0])
    );
    const search = new URLSearchParams();
    entries.forEach(([key, value]) => search.append(key, value));
    return search.toString();
  }

  function getCsrfToken() {
    try {
      const raw = document.body.getAttribute('hx-headers');
      if (raw) {
        const parsed = JSON.parse(raw);
        return parsed['X-CSRFToken'] || '';
      }
    } catch (_) {}
    return '';
  }

  async function signRequest(method, path, bodyString) {
    const resp = await fetch('/auth/sign', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      credentials: 'same-origin',
      body: JSON.stringify({ method, path, body_string: bodyString || '' }),
    });
    if (!resp.ok) {
      return null;
    }
    return resp.json();
  }

  document.body.addEventListener('htmx:configRequest', function (evt) {
    const { headers, parameters, verb, path } = evt.detail;
    if (!['POST', 'PUT', 'DELETE'].includes(verb)) {
      return;
    }
    if (headers['X-Signature']) {
      return;
    }
    evt.detail.elt._hmacPending = {
      verb,
      path,
      parameters: Object.assign({}, parameters),
    };
  });

  document.body.addEventListener('htmx:beforeRequest', function (evt) {
    const elt = evt.detail.elt;
    if (!elt._hmacPending) {
      return;
    }
    const pending = elt._hmacPending;
    delete elt._hmacPending;
    evt.preventDefault();

    const bodyString = buildBodyStringFromParams(pending.parameters);
    signRequest(pending.verb, pending.path, bodyString).then(function (result) {
      if (!result) {
        return;
      }
      htmx.ajax(pending.verb, pending.path, {
        source: elt,
        values: pending.parameters,
        headers: {
          'X-Signature': result.signature,
          'X-Timestamp': result.timestamp,
          'X-Nonce': result.nonce,
        },
      });
    });
  });

  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (
      form.hasAttribute('hx-post') ||
      form.hasAttribute('hx-put') ||
      form.hasAttribute('hx-delete')
    ) {
      return;
    }
    const method = (form.getAttribute('method') || 'GET').toUpperCase();
    if (!['POST', 'PUT', 'DELETE'].includes(method)) {
      return;
    }
    event.preventDefault();
    const action = form.getAttribute('action') || window.location.pathname;
    const bodyString = buildBodyStringFromForm(form);
    const result = await signRequest(method, action, bodyString);
    if (!result) {
      form.submit();
      return;
    }
    const formData = new FormData(form);

    const response = await fetch(action, {
      method,
      body: formData,
      headers: {
        'X-Signature': result.signature,
        'X-Timestamp': result.timestamp,
        'X-Nonce': result.nonce,
      },
      credentials: 'same-origin',
    });

    if (response.redirected) {
      window.location.href = response.url;
      return;
    }
    const contentType = response.headers.get('Content-Type') || '';
    if (contentType.includes('text/html')) {
      const html = await response.text();
      document.documentElement.innerHTML = html;
    } else {
      window.location.reload();
    }
  });
})();
