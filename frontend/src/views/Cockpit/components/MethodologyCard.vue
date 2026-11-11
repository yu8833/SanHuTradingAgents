<script setup lang="ts">
defineOptions({ name: 'CockpitMethodologyCard' })
import { ref } from 'vue'
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue'

const open = ref(false)
</script>

<template>
  <div class="cme-card" :class="{ 'is-open': open }">
    <div class="cme-head" @click="open = !open">
      <span class="cme-no">00</span>
      <span class="cme-title">怎么用这个页面买卖股票（方法论）</span>
      <span class="cme-sub">不预测涨跌，只做「左侧观察 → 右侧确认 → 纪律离场」</span>
      <el-icon class="cme-arrow">
        <ArrowUp v-if="open" />
        <ArrowDown v-else />
      </el-icon>
    </div>

    <div v-show="open" class="cme-body">
      <div class="cme-premise">
        市场的顶和底无法被预测。凡是「涨跌预测」本质上都是后视镜。
        能做的只有一件事：<b>在下跌里等它止跌横盘（左侧观察），在放量突破时确认趋势（右侧确认），然后按纪律拿住或走人。</b>
      </div>

      <div class="cme-steps">
        <div class="cme-step">
          <div class="cme-step-head"><span class="cme-step-no">1</span>环境闸门 —— 先看今天能不能打</div>
          <p>大盘画像（8 类）× 短线情绪阶段（7 类）决定总仓位。红灯空仓，黄灯轻仓试错，绿灯按信号进攻。环境不对，下面看到的机会都不做。</p>
        </div>
        <div class="cme-step">
          <div class="cme-step-head"><span class="cme-step-no">2</span>主线方向 —— 只在资金持续流入的方向里挑</div>
          <p>同花顺 90 行业里，3/5/10/20 日累计净额连续为正的方向才叫主线。不在主线里的票，即使形态好看也不碰——集中兵力。</p>
        </div>
        <div class="cme-step">
          <div class="cme-step-head"><span class="cme-step-no">3</span>积累区观察池 —— B1 ∩ 积累区，左侧观察不买</div>
          <p>与全市场 B1 左侧买点取交集：B1 是全集（BIAS60 深度超跌），积累区是精选。入池四条件：① 近 20 日不创新低（允许 2% 弹簧下探）；② 当前波动率处于自身近 250 日低分位（&lt;40%）；③ 近 15 日振幅比近 60 日收缩 10% 以上；④ 20 日日均成交额 ≥ 1 亿（有流动性）。<br />既有左侧信号、又满足吸筹形态。此时只看，不动手。</p>
        </div>
        <div class="cme-step">
          <div class="cme-step-head"><span class="cme-step-no">4</span>B2 突破买点 —— 右侧确认，才买</div>
          <p>与 Candidate 页同一真源：放量 + 中阳 + 站上 MA55/MA60（B2 突破买点）。不再另用「触发价 + 量比」规则。<br /><b>触发一只买一只，不提前埋伏、不追高补仓。</b>盘中每 15 分钟按 B2 扫描，确认后推送到通知。</p>
        </div>
        <div class="cme-step">
          <div class="cme-step-head"><span class="cme-step-no">5</span>纪律离场 —— 不猜顶，按条件走</div>
          <p>统一优先级：假突破（跌破触发价 2%）→ 止损（计划价与 -8% 取更紧）→ 三买三卖卖点（S3/S2/S1/SafetyNet/TrailingStop）→ 收盘跌破 MA5 → 止盈 +15% 或回到 MA20 附近 → 时间止损（超 30 天）。<br />盘中跌破 MA5 只预警（不被日内洗盘洗出），收盘确认才离场。T+1：当日买入不能卖。</p>
        </div>
      </div>

      <div class="cme-warn">
        当前入池参数为经验值（<b>exp-v2</b>），已按 2026-11 市场分布校准，但<b>尚未经过完整回测</b>。把它当作纪律框架，而不是收益承诺。
      </div>
    </div>
  </div>
</template>

<style scoped>
.cme-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-bg-color);
  overflow: hidden;
}
.cme-card.is-open { border-color: var(--el-color-primary-light-5); }
.cme-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  flex-wrap: wrap;
}
.cme-head:hover { background: var(--el-fill-color-lighter); }
.cme-no {
  font-size: 11px;
  font-weight: 700;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 4px;
  padding: 2px 7px;
}
.cme-title { font-size: 14px; font-weight: 600; }
.cme-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex: 1;
  min-width: 200px;
}
.cme-arrow { color: var(--el-text-color-secondary); }
.cme-body { padding: 0 16px 16px; }
.cme-premise {
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-lighter);
  border-left: 3px solid var(--el-color-primary);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 14px;
}
.cme-steps {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}
.cme-step {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--el-bg-color);
}
.cme-step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.cme-step-no {
  width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 50%;
  font-size: 11px;
  color: #fff;
  background: var(--el-color-primary);
  flex: 0 0 auto;
}
.cme-step p {
  margin: 0;
  font-size: 12px;
  line-height: 1.75;
  color: var(--el-text-color-secondary);
}
.cme-warn {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.7;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 8px 12px;
}
</style>
