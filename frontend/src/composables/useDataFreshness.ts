/**
 * 数据新鲜度检查 composable
 *
 * 在选股扫描前检查数据是否最新，如果过期则提示用户并提供更新按钮
 */
import { ref } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { screeningApi } from '@/api/screening'

export interface DataFreshnessInfo {
  latest_data_date: string | null
  expected_date: string
  is_fresh: boolean
  stale_days: number
  total_stocks: number
  expected_total: number
  message: string
}

export function useDataFreshness() {
  const checking = ref(false)
  const freshnessInfo = ref<DataFreshnessInfo | null>(null)

  /**
   * 检查数据新鲜度
   * @returns DataFreshnessInfo | null
   */
  async function checkFreshness(): Promise<DataFreshnessInfo | null> {
    checking.value = true
    try {
      const resp = await screeningApi.checkDataFreshness()
      freshnessInfo.value = resp.data
      return resp.data
    } catch (e: any) {
      console.error('[data-freshness] 检查失败:', e)
      return null
    } finally {
      checking.value = false
    }
  }

  /**
   * 在扫描前检查数据新鲜度
   * 如果数据过期，弹窗提示用户选择：更新数据 / 继续扫描 / 取消
   *
   * @returns Promise<boolean> - true 表示可以继续扫描，false 表示取消
   */
  async function checkBeforeScan(): Promise<boolean> {
    const info = await checkFreshness()
    if (!info) {
      // 检查失败，允许继续扫描
      return true
    }

    if (info.is_fresh) {
      // 数据最新，直接扫描
      return true
    }

    // 数据过期，弹窗提示
    const staleText = info.stale_days >= 999
      ? '数据库中无历史K线数据'
      : `数据已过期 ${info.stale_days} 天`

    const latestDate = info.latest_data_date || '无数据'
    const coverage = info.expected_total > 0
      ? `${info.total_stocks}/${info.expected_total} 只股票有数据`
      : ''

    try {
      const action = await ElMessageBox.confirm(
        `<div style="line-height: 1.8;">
          <p style="font-size: 15px; margin-bottom: 8px;">
            <strong>${staleText}</strong>
          </p>
          <p style="color: #909399; margin-bottom: 4px;">
            最新数据日期：<strong>${latestDate}</strong>
          </p>
          ${coverage ? `<p style="color: #909399; margin-bottom: 4px;">数据覆盖：${coverage}</p>` : ''}
          <p style="color: #E6A23C; margin-top: 8px;">
            使用过期数据扫描可能导致结果不准确，建议先更新数据。
          </p>
        </div>`,
        '数据过期提醒',
        {
          dangerouslyUseHTMLString: true,
          distinguishCancelAndClose: true,
          confirmButtonText: '更新数据',
          cancelButtonText: '继续扫描',
          type: 'warning',
        }
      )

      // 用户点击"更新数据"
      if (action === 'confirm') {
        // 触发历史数据同步
        await triggerDataSync()
        return false // 不继续扫描，等同步完成后再扫
      }

      return true
    } catch (action: any) {
      // 用户点击"继续扫描"（cancel）或关闭（close）
      if (action === 'cancel') {
        return true
      }
      // 关闭按钮
      return false
    }
  }

  /**
   * 触发数据同步
   */
  async function triggerDataSync() {
    try {
      ElMessage.info('正在触发历史数据同步，请稍后...')

      // 调用 scheduler API 触发 tushare 历史同步
      const token = localStorage.getItem('auth-token')
      const resp = await fetch('/api/scheduler/jobs/tushare_historical_sync/trigger?force=true', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })
      const data = await resp.json()

      if (data.success !== false) {
        ElMessage.success('数据同步任务已触发，预计需要数小时完成。您可以先使用现有数据扫描，稍后再重新扫描。')
      } else {
        ElMessage.warning(data.message || '触发同步失败，请稍后手动重试')
      }
    } catch (e: any) {
      console.error('[data-freshness] 触发同步失败:', e)
      ElMessage.error('触发数据同步失败，请稍后重试')
    }
  }

  return {
    checking,
    freshnessInfo,
    checkFreshness,
    checkBeforeScan,
    triggerDataSync,
  }
}
