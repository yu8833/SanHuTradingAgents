/**
 * HTML 净化工具
 *
 * 所有通过 v-html 渲染的内容（Markdown 转换结果、AI 输出、文章正文等）
 * 必须先经过 sanitizeHtml 净化，以防止 XSS 攻击：
 *   - 移除 <script>、<iframe>、<object>、<embed> 等危险标签
 *   - 移除 on* 事件属性（onclick、onerror 等）
 *   - 移除 javascript: 协议链接
 *
 * 基于 DOMPurify（业界标准 HTML 净化库）。
 */
import DOMPurify from 'dompurify'

// 允许的标签：覆盖 Markdown 常见输出 + 文章正文所需
// DOMPurify 默认已禁止 script/iframe/object/embed 等，这里显式声明 ALLOWED_TAGS
// 以便在保留 Markdown 排版能力的同时收紧白名单。
const ALLOWED_TAGS = [
  // 文本基础
  'p', 'br', 'hr', 'span', 'div',
  // 标题
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  // 文本格式
  'strong', 'b', 'em', 'i', 'u', 's', 'del', 'mark', 'sub', 'sup', 'small',
  // 引用
  'blockquote', 'q', 'cite',
  // 列表
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  // 链接与图片
  'a', 'img',
  // 代码
  'code', 'pre', 'kbd', 'samp',
  // 表格
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
  // 其他
  'figure', 'figcaption', 'details', 'summary',
]

// 允许的属性：覆盖 Markdown 输出所需属性
const ALLOWED_ATTR = [
  'href', 'title', 'alt', 'src', 'width', 'height',
  'class', 'id',
  'colspan', 'rowspan',
  'target', 'rel',
  'start', 'type',  // 有序列表
  'open',           // details
]

// 净化配置
const SANITIZE_CONFIG: DOMPurify.Config = {
  ALLOWED_TAGS,
  ALLOWED_ATTR,
  // 禁止所有 data: URI（防止 data:text/html 等攻击）
  ALLOW_DATA_ATTR: false,
  // 禁止未知协议
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|#|\/)/i,
  // 给所有外部链接强制添加安全属性
  FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick'],
}

/**
 * 净化 HTML 字符串，移除 XSS 危险内容
 *
 * @param html 待净化的 HTML 字符串（可能为空或非字符串）
 * @returns 净化后的安全 HTML 字符串
 *
 * @example
 *   <div v-html="sanitizeHtml(renderMarkdown(content))"></div>
 */
export function sanitizeHtml(html: unknown): string {
  if (html == null) return ''
  const input = typeof html === 'string' ? html : String(html)
  if (!input) return ''
  try {
    return DOMPurify.sanitize(input, SANITIZE_CONFIG) as unknown as string
  } catch {
    // 净化失败时，退化为 HTML 转义，绝不放行未净化内容
    return input
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
  }
}
