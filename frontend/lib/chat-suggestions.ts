export type Suggestion = {
  icon: string;
  label: string;
  /** 点击后作为用户消息发送的文本；action 为 upload 时可省略 */
  prompt?: string;
  /** 特殊行为：upload = 打开简历文件选择器 */
  action?: 'upload';
};

/** 空会话 / 无会话欢迎屏的建议卡片（2 列网格） */
export const EMPTY_STATE_SUGGESTIONS: Suggestion[] = [
  { icon: '📄', label: '上传简历，智能匹配岗位', action: 'upload' },
  {
    icon: '💼',
    label: '我会 Python 和 React，帮我找远程兼职',
    prompt: '我会 Python 和 React，帮我找远程兼职',
  },
  { icon: '🔍', label: '有哪些海外客服类的兼职岗位？', prompt: '有哪些海外客服类的兼职岗位？' },
  { icon: '💰', label: '时薪 $20 以上的岗位有哪些？', prompt: '时薪 $20 以上的岗位有哪些？' },
  {
    icon: '⏰',
    label: '我每周只能工作 15 小时，有什么合适的？',
    prompt: '我每周只能工作 15 小时，有什么合适的？',
  },
  { icon: '👤', label: '查看我的档案和求职偏好', prompt: '查看我的档案和求职偏好' },
];

/** 输入框上方常驻快捷指令 chip */
export const QUICK_ACTIONS: Suggestion[] = [
  { icon: '📎', label: '上传简历', action: 'upload' },
  { icon: '🔍', label: '搜索岗位', prompt: '帮我搜索适合我的兼职岗位' },
  { icon: '🎯', label: '开始匹配', prompt: '根据我的档案帮我匹配岗位' },
  { icon: '👤', label: '我的档案', prompt: '查看我的档案和求职偏好' },
  { icon: '⚙️', label: '调整偏好', prompt: '我想调整我的求职偏好' },
];

/** 追问建议：按上一轮工具调用名选择，无工具调用时用 default */
export const FOLLOW_UPS: Record<string, string[]> = {
  run_matches: ['换一批岗位', '调整我的偏好', '讲讲第一个岗位'],
  parse_resume: ['根据简历帮我匹配岗位', '我的技能识别对吗？'],
  search_jobs: ['按匹配度排序', '只看远程岗位'],
  update_preferences: ['用新偏好重新匹配'],
  get_my_profile: ['更新我的求职偏好', '开始匹配岗位'],
  default: ['帮我匹配岗位', '现在有哪些兼职岗位？'],
};
