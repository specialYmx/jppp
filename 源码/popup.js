document.getElementById('extractBtn').addEventListener('click', async () => {
  const statusDiv = document.getElementById('status');
  const fallbackTextarea = document.getElementById('fallbackTextarea');

  statusDiv.innerText = "正在获取 Token...";
  statusDiv.style.color = "#666";
  fallbackTextarea.style.display = "none";

  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (!tab.url.includes("chatgpt.com")) {
    statusDiv.innerText = "❌ 请先打开 ChatGPT 网页";
    statusDiv.style.color = "red";
    return;
  }

  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: fetchSessionData
  }, async (results) => {
    if (chrome.runtime.lastError || !results || !results[0].result) {
      statusDiv.innerText = "❌ 提取失败，请刷新页面重试";
      statusDiv.style.color = "red";
      return;
    }

    const resultData = results[0].result;

    if (resultData.startsWith("ERROR:")) {
        statusDiv.innerText = "❌ " + resultData.replace("ERROR:", "");
        statusDiv.style.color = "red";
        return;
    }

    try {
      await navigator.clipboard.writeText(resultData);
      statusDiv.innerText = "✅ 提取成功！已复制到剪贴板。";
      statusDiv.style.color = "#10a37f";
    } catch (err) {
      statusDiv.innerText = "⚠️ 自动复制失败，请手动复制：";
      statusDiv.style.color = "#d97706";
      fallbackTextarea.style.display = "block";
      fallbackTextarea.value = resultData;
      fallbackTextarea.select();
    }
  });
});

// 注入到网页中执行：核心获取逻辑与 JWT 伪造
async function fetchSessionData() {
  try {
    const res = await fetch('https://chatgpt.com/api/auth/session');
    if (!res.ok) return "ERROR:网络请求失败，请检查登录状态";

    const sessionData = await res.json();
    if (!sessionData || !sessionData.accessToken) {
      return "ERROR:未获取到 Token，请确认已登录";
    }

    const email = sessionData.user?.email || "unknown@outlook.com";
    const now = Math.floor(Date.now() / 1000);

    const base64UrlEncode = (str) => {
      return btoa(unescape(encodeURIComponent(str)))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');
    };

    // 满配版 Payload：应对强类型后端的严格解析检查
    const fakePayload = {
      aud: ["app_default_client"],
      iss: "https://auth.openai.com",
      amr: ["pwd"],
      auth_provider: "auth0",
      email: email,
      email_verified: true,
      name: sessionData.user?.name || email.split('@')[0],
      iat: now,
      exp: now + 31536000,             // 过期时间 (1年)
      sub: sessionData.user?.id || "auth0|dummy_user_id"
    };

    const header = base64UrlEncode(JSON.stringify({ alg: "HS256", typ: "JWT" }));
    const payload = base64UrlEncode(JSON.stringify(fakePayload));

    // 拼接成完整的高仿 id_token
    const fakeIdToken = `${header}.${payload}.dummy_signature_xyz123`;

    // 构造最终输出数据
    const exportedData = {
      "tokens": {
        "id_token": fakeIdToken,                   // 伪造的完美格式 id_token
        "access_token": sessionData.accessToken,   // 真实的 access_token (用于干活)
        "refresh_token": "rt_dummy_token_123"      // 常规的防空占位符
      }
    };

    return JSON.stringify(exportedData, null, 2);
  } catch (err) {
    return "ERROR:" + err.message;
  }
}