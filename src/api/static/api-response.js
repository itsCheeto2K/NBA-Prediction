// Read API errors safely even when a server/proxy responds with plain text or HTML.
async function readApiResponse(response) {
  const body = await response.text();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}. Please check the API server logs.`);
    }
    throw new Error("Server returned an invalid JSON response. Please try again.");
  }
  if (!response.ok) {
    const detail = data && data.detail;
    let message;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) {
      message = detail.map(item => typeof item === "string" ? item : item.msg).filter(Boolean).join("; ");
    }
    throw new Error(message || `Server returned HTTP ${response.status}`);
  }
  return data;
}
