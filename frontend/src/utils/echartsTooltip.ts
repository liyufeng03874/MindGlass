/**
 * ECharts 6 移除了字符串模板里的 {@字段} 自定义属性访问语法（{b}/{c} 等内置变量仍支持）。
 * 这里把 tooltip.formatter 字符串里的 {@key} 编译成函数 formatter，兼容 ECharts 6。
 *
 * 用法：setOption 前调用 fixTooltipFormatter(option)，返回处理后的 option。
 */
export function fixTooltipFormatter(option: any): any {
  const tf = option?.tooltip?.formatter
  if (typeof tf !== 'string') return option
  if (!tf.includes('{@')) return option

  const compiled = (params: any) => {
    const data = params?.data ?? {}
    const obj = (typeof data === 'object' && data !== null) ? data : {}
    const valueObj = (typeof obj.value === 'object' && obj.value !== null) ? obj.value : {}
    const name = params?.name ?? params?.seriesName ?? ''
    const value = params?.value ?? ''
    const v = (k: string) => {
      const val = obj[k] ?? valueObj[k]
      return (val === undefined || val === null) ? '' : String(val)
    }
    return tf
      .replace(/\{@(\w+)\}/g, (_m: string, k: string) => v(k))
      .replace(/\{b\}/g, String(name))
      .replace(/\{c\}/g, String(value))
      .replace(/\{a\}/g, String(params?.seriesName ?? ''))
  }
  option.tooltip.formatter = compiled
  return option
}
