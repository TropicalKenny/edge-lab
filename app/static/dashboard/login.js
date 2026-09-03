(() => {
  const sendButton = document.getElementById('send-code');
  const form = document.getElementById('verify-form');
  const codeInput = document.getElementById('code');
  const status = document.getElementById('status');
  let challengeId = '';

  const setStatus = (message, kind = '') => {
    status.textContent = message;
    status.className = `status ${kind}`.trim();
  };

  const parseError = async (response) => {
    try {
      const body = await response.json();
      return body.detail || 'Request failed.';
    } catch {
      return 'Request failed.';
    }
  };

  sendButton.addEventListener('click', async () => {
    sendButton.disabled = true;
    setStatus('Sending code…');
    try {
      const response = await fetch('/auth/request-otp', {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const body = await response.json();
      challengeId = body.challenge_id;
      form.hidden = false;
      codeInput.focus();
      setStatus('Code sent. It expires in 10 minutes.', 'success');
      sendButton.textContent = 'Send another code';
    } catch (error) {
      setStatus(error.message || 'Unable to send code.', 'error');
    } finally {
      sendButton.disabled = false;
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!challengeId) {
      setStatus('Request a new code first.', 'error');
      return;
    }

    const code = codeInput.value.trim();
    if (!/^\d{6}$/.test(code)) {
      setStatus('Enter the 6-digit code.', 'error');
      return;
    }

    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    setStatus('Verifying…');
    try {
      const response = await fetch('/auth/verify-otp', {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ challenge_id: challengeId, code }),
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      window.location.assign('/dashboard');
    } catch (error) {
      codeInput.select();
      setStatus(error.message || 'Unable to verify code.', 'error');
    } finally {
      submit.disabled = false;
    }
  });
})();
