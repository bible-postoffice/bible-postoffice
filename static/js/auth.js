async function handleLogin(supabaseToken) {
    try {
        const res = await fetch('/auth/check-user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: supabaseToken })
        });
        const data = await res.json();
        if (data.success) window.location.href = data.redirect_url;
    } catch (err) {
        console.error("에러 발생:", err);
    }
}