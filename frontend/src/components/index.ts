import type { App } from 'vue'
import MarketSelector from './Global/MarketSelector.vue'
import MultiMarketStockSearch from './Global/MultiMarketStockSearch.vue'
import StockLink from './StockLink.vue'

// 全局组件注册
export function setupGlobalComponents(app: App) {
  // 注册多市场相关组件
  app.component('MarketSelector', MarketSelector)
  app.component('MultiMarketStockSearch', MultiMarketStockSearch)
  // 股票代码/名称统一链接（跳转股票详情页）
  app.component('StockLink', StockLink)
}

export default setupGlobalComponents
