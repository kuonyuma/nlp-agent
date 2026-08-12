export const APP_NAME = "NLP 学习助手";

export const APP_VERSION = "v1.1.1";

export const APP_VERSION_DATE = "2026-07-25";

export const APP_RELEASE_NOTES = [
  "新增固定凭证登录与账号管理，学生会话需登录后才能新建并安全保存记录。",
  "新增多模型支持：设置中可切换 DeepSeek、Qwen 等学生模型。",
  "引入角色权限（RBAC）与资源级授权控制，并记录授权审计。",
  "会话、记忆与观测数据迁移到 MySQL 持久化存储，支持数据库迁移基线。",
  "新增 Nova 边缘反向代理与自动化交付流水线（CI/CD）。",
  "讲解模式补充代码引导，并强化 Coordinator / Worker 提示词。",
  "优化登录页与未登录时的学生布局体验。",
];

export const APP_IS_CURRENT = true;