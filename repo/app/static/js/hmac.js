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

  async function sha256HexFromText(text) {
    const data = new TextEncoder().encode(text || '');
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    return [...new Uint8Array(hashBuffer)]
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('');
  }

  async function sha256HexFromFile(file) {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    return [...new Uint8Array(hashBuffer)]
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('');
  }

  async function buildBodyPayloadFromForm(form) {
    const formData = new FormData(form);
    const entries = [];
    const fileEntries = [];

    for (const [key, value] of formData.entries()) {
      if (value instanceof File) {
        fileEntries.push({ key, file: value });
      } else {
        entries.push([key, value]);
      }
    }

    entries.sort((a, b) =>
      a[0] === b[0]
        ? String(a[1]).localeCompare(String(b[1]))
        : a[0].localeCompare(b[0])
    );

    const search = new URLSearchParams();
    entries.forEach(([key, value]) => search.append(key, value));
    const bodyString = search.toString();

    if (!fileEntries.length) {
      return {
        bodyString,
        bodyHash: await sha256HexFromText(bodyString),
      };
    }

    const normalizedFiles = [];
    for (const { key, file } of fileEntries) {
      if (!file || !file.name) {
        continue;
      }
      normalizedFiles.push({
        key,
        name: file.name,
        type: file.type || '',
        size: file.size || 0,
        hash: await sha256HexFromFile(file),
      });
    }

    normalizedFiles.sort((a, b) => {
      if (a.key !== b.key) {
        return a.key.localeCompare(b.key);
      }
      if (a.name !== b.name) {
        return a.name.localeCompare(b.name);
      }
      if (a.type !== b.type) {
        return a.type.localeCompare(b.type);
      }
      return a.size - b.size;
    });

    if (!normalizedFiles.length) {
      return {
        bodyString,
        bodyHash: await sha256HexFromText(bodyString),
      };
    }

    const fileLines = normalizedFiles.map(
      (item) =>
        `${item.key}\t${item.name}\t${item.type}\t${item.size}\t${item.hash}`
    );
    const canonical = `${bodyString}\n--files--\n${fileLines.join('\n')}`;
    return {
      bodyString,
      bodyHash: await sha256HexFromText(canonical),
    };
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

  async function signRequest(method, path, payload) {
    const resp = await fetch('/auth/sign', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      credentials: 'same-origin',
      body: JSON.stringify({
        method,
        path,
        body_string: payload?.bodyString || '',
        body_hash: payload?.bodyHash || '',
      }),
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

    const form = elt instanceof HTMLFormElement ? elt : elt.closest('form');
    const payloadPromise = form
      ? buildBodyPayloadFromForm(form)
      : Promise.resolve({ bodyString: buildBodyStringFromParams(pending.parameters) });

    payloadPromise.then(function (payload) {
      signRequest(pending.verb, pending.path, payload).then(function (result) {
        if (!result) {
          return;
        }
        const requestOptions = {
          source: form || elt,
          headers: {
            'X-Signature': result.signature,
            'X-Timestamp': result.timestamp,
            'X-Nonce': result.nonce,
          },
        };
        if (!form) {
          requestOptions.values = pending.parameters;
        }
        htmx.ajax(pending.verb, pending.path, requestOptions);
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
    const payload = await buildBodyPayloadFromForm(form);
    const result = await signRequest(method, action, payload);
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
      const isFullDocument = /<html[\s>]/i.test(html) && /<body[\s>]/i.test(html);
      if (isFullDocument) {
        document.documentElement.innerHTML = html;
      } else {
        window.location.reload();
      }
    } else {
      window.location.reload();
    }
  });
})();
