export function getFriendlyErrorMessage(error, fallbackMessage = "请求失败。") {
  const detail = error.response?.data?.detail;
  const status = error.response?.status;
  const code = error.code;
  const message = error.message;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item?.msg)
      .filter(Boolean);
    return messages.length
      ? `输入内容不符合要求：${messages.join("；")}`
      : "请求内容不符合后端校验要求。";
  }

  if (detail && typeof detail === "object") {
    const detailMessage = detail.message || fallbackMessage;
    if (status === 429) {
      const usage = [];
      if (detail.used !== undefined && detail.limit !== undefined) {
        usage.push(`已使用 ${detail.used}/${detail.limit}`);
      }
      if (detail.remaining !== undefined) {
        usage.push(`剩余 ${detail.remaining}`);
      }
      if (detail.reset_at) {
        usage.push(`重置时间 ${detail.reset_at}`);
      }
      return usage.length ? `${detailMessage}（${usage.join("，")}）` : detailMessage;
    }
    return detailMessage;
  }

  if (code === "ECONNABORTED") {
    return "请求超时。可能是模型生成、向量检索或联网搜索耗时较长，请稍后重试。";
  }

  if (!status && message === "Network Error") {
    return "无法连接后端服务。请确认 FastAPI 后端已经启动，并检查地址是否为 http://127.0.0.1:8000。";
  }

  if (status === 400) {
    return "请求参数有误，请检查输入内容。";
  }

  if (status === 401) {
    return "登录状态已失效，请重新登录。";
  }

  if (status === 403) {
    return "当前账号没有权限执行此操作。";
  }

  if (status === 409) {
    return "当前操作与会话状态冲突，页面将重新读取最新状态。";
  }

  if (status === 429) {
    return "今日额度已用完，请在额度重置后再试。";
  }

  if (status === 404) {
    return "接口不存在，请检查后端路由是否注册成功。";
  }

  if (status === 422) {
    return "请求格式不符合后端接口要求，请检查字段名和数据类型。";
  }

  if (status >= 500) {
    return "后端服务内部错误，请查看后端终端日志。";
  }

  return fallbackMessage;
}
