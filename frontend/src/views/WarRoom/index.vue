<template>
  <div class="war-room app-page">
    <!-- ═══ 顶栏：日期 + 实时状态 + 刷新 ═══ -->
    <div class="wr-top">
      <div class="wr-head">
        <h2 class="wr-title">今日作战</h2>
        <span class="wr-date">{{ todayText }}</span>
      </div>
      <div class="wr-actions">
        <span class="live" :class="{ on: liveOn }">
          <i class="live-dot"></i>{{ liveOn ? '实时更新中' : '等待行情…' }}
        </span>
        <el-button size="small" text :icon="Refresh" :loading="loading" @click="refreshCurrent">刷新</el-button>
        <el-button size="small" text @click="goScheduled">定时任务</el-button>
      </div>
    </div>

    <!-- ═══ 大盘方向条 ═══ -->
    <section class="macro-bar" :class="macroCls">
      <div class="macro-main">
        <em class="macro-pill">{{ statusLabel(basis?.status) }}</em>
        <span class="macro-conf">置信度 <b>{{ basis?.confidence ?? '—' }}%</b></span>
      </div>
      <div class="macro-advice">{{ macroAdvice }}</div>
      <div class="macro-gauge" title="刻度 = 状态区间 · 指针 = 当日基准得分">
        <div class="g-seg bear">偏空</div>
        <div class="g-seg neu">中性</div>
        <div class="g-seg bull">偏多</div>
        <div class="g-needle" :style="{ left: gaugePos + '%' }"></div>
      </div>
      <div class="macro-meta">
        <template v-if="macro">快照 {{ fmtClock(macro.created_at) }}</template>
        <template v-else-if="macroAutoGenerating">正在自动生成大盘快照…</template>
        <template v-else>大盘快照未生成</template>
      </div>
      <!-- 打分依据 · 折叠（与方向条融为一体，展开逐条复核） -->
      <div v-if="signals.length" class="macro-facts" :class="{ open: signalOpen }" @click="signalOpen = !signalOpen">
        <span class="mf-label">打分依据</span>
        <span class="mf-sum">总分 <b>{{ basis?.score ?? '—' }}</b><em v-if="scoreBreakdown" class="mf-brk">（{{ scoreBreakdown }}）</em><i class="mf-th">偏多≥+2 · 偏空≤-2</i></span>
        <span class="flex"></span>
        <i class="mf-arrow" :class="{ open: signalOpen }"></i>
      </div>
      <div v-show="signalOpen" class="ms-list">
        <!-- A · 大盘信号：指数/期货/情绪 紧凑行，分值徽章醒目 -->
        <div v-for="(s, i) in indexSignals" :key="i" class="ms-row" :class="['score-' + sigScoreCls(s), { hot: sigScore(s) !== 0 }]">
          <span class="ms-name">{{ s.name }}</span>
          <span class="ms-val">{{ fmtSigValue(s) }}</span>
          <b class="ms-score" :class="sigScoreCls(s)">{{ fmtSigScore(s) }}</b>
          <span class="ms-detail">{{ s.detail }}</span>
        </div>

        <!-- B · 重要事件：重大新闻（|影响度|≥50）融合为事件卡，可独立折叠 -->
        <div class="ms-news" :class="{ open: newsOpen }">
          <div class="ms-news-head" @click="newsOpen = !newsOpen">
            <i class="mf-arrow" :class="{ open: newsOpen }"></i>
            <span class="ms-news-title">重要事件<em class="ms-news-sub">已计入总分 · 打分 / 解读 / 板块</em></span>
            <span class="flex"></span>
            <span class="ms-news-count">{{ eventSignals.length }} 条</span>
            <el-button v-if="eventSignals.length > 5" size="small" text @click.stop="evLimit = evLimit >= eventSignals.length ? 5 : eventSignals.length">
              {{ evLimit >= eventSignals.length ? '展开全部' : '收起' }}
            </el-button>
          </div>
          <div v-show="newsOpen">
            <div v-if="shownEvents.length" class="ev-cards">
              <div v-for="(s, i) in shownEvents" :key="i" class="ev-card" :class="evDir(s)">
                <div class="ev-side">
                  <em class="ev-dir" :class="evDir(s)">{{ evDirText(s) }}</em>
                  <b class="ev-score" :class="evScoreCls(s)">{{ evScoreText(s) }}</b>
                  <span class="ev-lv">{{ evLevel(s) }}影响</span>
                </div>
                <div class="ev-main">
                  <div class="ev-meta">
                    <el-tag v-if="evDetail(s)?.category" size="small" class="cat-tag" effect="plain">{{ evDetail(s)?.category }}</el-tag>
                    <el-tag :type="importanceTag(evDetail(s)?.importance)" size="small" effect="plain">{{ evDetail(s)?.importance === 'high' ? '重大' : evDetail(s)?.importance === 'medium' ? '重要' : '一般' }}</el-tag>
                    <span v-if="evDetail(s)?.source" class="ev-src">{{ sourceShort(evDetail(s)?.source) }} · {{ newsTime(evDetail(s)?.publish_time) }}</span>
                  </div>
                  <p class="ev-title">
                    <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer" class="ev-origin">{{ s.title }} →</a>
                    <span v-else>{{ s.title }}</span>
                  </p>
                  <p v-if="evDetail(s)?.analysis" class="ev-analysis">{{ evDetail(s)?.analysis }}</p>
                  <div v-if="evDetail(s)?.related_sectors?.length" class="ev-sectors">
                    <span class="sec-label">相关板块</span>
                    <span v-for="(sec, si) in evDetail(s)?.related_sectors" :key="si" class="sec-chip">{{ sec }}</span>
                  </div>
                </div>
              </div>
            </div>
            <p v-else class="ms-news-empty">今日暂无计入总分的强影响事件</p>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ 今日操作 · 总览条（先给全局结论，再进双栏明细） ═══ -->
    <section class="ops-bar">
      <span class="ops-label">今日操作</span>
      <span class="ops-count is-buy"><i></i>买入 {{ opsBuy }}</span>
      <span class="ops-count is-hold"><i></i>观望 {{ opsHold }}</span>
      <span class="ops-count is-sell"><i></i>卖出 {{ opsSell }}</span>
      <span class="flex"></span>
      <span class="ops-time">{{ liveOn ? '实时更新中 · ' : '等待行情 · ' }}{{ lastUpdateText }}</span>
    </section>

    <!-- ═══ 决策板：左买右卖 ═══ -->
    <div class="wr-grid">
      <!-- ── 今日买入 ── -->
      <section class="zone zone-buy">
        <header class="zone-head">
          <div class="zh-left">
            <h3>今日买入</h3>
            <span class="zone-sub">买什么 · 什么价格买</span>
          </div>
          <span class="zone-count">{{ buyList.length }}</span>
        </header>

        <el-alert v-if="quotesUnavailable" type="warning" :closable="false" show-icon class="zone-alert">
          实时行情暂不可用，以下是基于信号快照价的条件，点「刷新」重试
        </el-alert>

        <div v-if="buyList.length" class="cards">
          <div v-for="(b, i) in buyList" :key="b.code + i" class="card buy-card" :class="'st-' + buyStatus(b)">
            <div class="card-top">
              <em class="chip" :class="buyChipCls(b)">{{ buyStatusText(b) }}</em>
              <a class="nm" :href="stockHref(b.code)" target="_blank" rel="noopener">{{ b.name || b.code }}</a>
              <span class="cd">{{ b.code }}</span>
              <span v-if="b.signal_label" class="tag">{{ b.signal_label }}</span>
              <span class="flex"></span>
              <!-- 候选（无 plan_id）可一键并入今日计划（已确认，进入盘中盯盘）；已有计划的无需重复 -->
              <el-button v-if="!b.plan_id" size="small" type="primary" plain :loading="addPlanCode === b.code" @click="addBuyToPlan(b)">加入计划</el-button>
              <el-button v-if="buyStatus(b) === 'exec'" size="small" type="danger" @click="goTrade(b)">去交易</el-button>
            </div>
            <div class="num-row">
              <div class="num"><k>现价</k><b :class="priceCls(b.last_price)">{{ b.last_price ?? '—' }}</b></div>
              <div class="num"><k>触发价</k><b>{{ b.trigger_price ?? '—' }}</b></div>
              <div class="num"><k>距触发</k><b :class="distCls(b.distance_pct)">{{ fmtPct(b.distance_pct) }}</b></div>
            </div>
            <div v-if="b.buy_reason" class="buy-reason">
              <span class="rs-label">买入理由</span>
              <span class="rs-text">{{ b.buy_reason }}</span>
            </div>
            <div class="cond">
              <em class="basis-mark" :class="basisCls(buyAdvice(b))">{{ basisIcon(buyAdvice(b)) }}</em>
              <span>{{ buyAdvice(b) }}</span>
            </div>
            <!-- 依据编号 · 点击展开明细 -->
            <div v-if="(b.reasons || []).length" class="rs-bar" :class="{ open: isReasonOpen('b', b.code, i) }" @click="toggleReasons('b', b.code, i)">
              <span class="rs-label">依据</span>
              <span class="rs-sum">{{ reasonCountText(b.reasons) }}</span>
              <span class="flex"></span>
              <i class="rs-arrow" :class="{ open: isReasonOpen('b', b.code, i) }"></i>
            </div>
            <div v-if="isReasonOpen('b', b.code, i)" class="rs-list">
              <div v-for="(r, ri) in (b.reasons || [])" :key="ri" class="rs-item">
                <em class="basis-mark" :class="reasonCls(r)">{{ reasonMark(r) }}</em>
                <span>{{ r.text }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="zone-empty">
          <template v-if="genPlanLoading">
            <p class="ze-t">正在自动生成当日计划…</p>
            <p class="ze-s">约 1~2 分钟，生成后自动出现在这里，无需操作</p>
            <el-progress :percentage="genPlanProgress" :stroke-width="6" style="max-width: 260px; margin: 6px auto 0;" />
          </template>
          <template v-else>
            <p class="ze-t">今日暂无买入标的</p>
            <p class="ze-s">盘前 8:15 自动生成候选；打开页面自动补生成，刷新即可看到</p>
          </template>
        </div>
      </section>

      <!-- ── 今日卖出 ── -->
      <section class="zone zone-sell">
        <header class="zone-head">
          <div class="zh-left">
            <h3>今日卖出</h3>
            <span class="zone-sub">卖什么 · 什么价格卖</span>
          </div>
          <span class="zone-count">{{ sellList.length }}</span>
        </header>

        <div v-if="sellUrgent.length" class="cards">
          <div v-for="(s, i) in sellUrgent" :key="s.code + i" class="card sell-card" :class="sellCardCls(s)">
            <div class="card-top">
              <em class="chip" :class="sellCardCls(s)">{{ sellStatusText(s) }}</em>
              <a class="nm" :href="stockHref(s.code)" target="_blank" rel="noopener">{{ s.name || s.code }}</a>
              <span class="cd">{{ s.code }}</span>
              <span class="flex"></span>
              <el-button size="small" type="danger" plain @click="decideSell(s)">决定卖出</el-button>
            </div>
            <div class="num-row">
              <div class="num"><k>现价</k><b>{{ s.last_price ?? '—' }}</b></div>
              <div class="num"><k>盈亏</k><b :class="priceCls(s.profit_loss_rate)">{{ s.profit_loss_rate != null ? fmtPct(s.profit_loss_rate) : '—' }}</b></div>
              <div class="num"><k>卖出价</k><b>{{ s.trigger_price ?? '—' }}</b></div>
            </div>
            <div class="cond act">
              <em class="basis-mark" :class="basisCls(sellReason(s))">{{ basisIcon(sellReason(s)) }}</em>
              <span class="act-pct">卖 {{ sellPctText(s) }}</span>
              <span v-if="s.trigger_price != null" class="act-trigger">触发 {{ s.trigger_price }}</span>
              <span class="act-reason">{{ sellReason(s) }}</span>
            </div>
            <!-- 依据编号 · 点击展开明细 -->
            <div v-if="(s.reasons || []).length" class="rs-bar" :class="{ open: isReasonOpen('s', s.code, i) }" @click="toggleReasons('s', s.code, i)">
              <span class="rs-label">依据</span>
              <span class="rs-sum">{{ reasonCountText(s.reasons) }}</span>
              <span class="flex"></span>
              <i class="rs-arrow" :class="{ open: isReasonOpen('s', s.code, i) }"></i>
            </div>
            <div v-if="isReasonOpen('s', s.code, i)" class="rs-list">
              <div v-for="(r, ri) in (s.reasons || [])" :key="ri" class="rs-item">
                <em class="basis-mark" :class="reasonCls(r)">{{ reasonMark(r) }}</em>
                <span>{{ r.text }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="!sellUrgent.length && !sellHolders.length" class="zone-empty">
          <p class="ze-t">暂无持仓，无需卖出</p>
          <p class="ze-s">买入成交后会自动进入这里的卖出评估</p>
        </div>

        <!-- 持有清单（折叠） -->
        <div v-if="sellHolders.length" class="holders">
          <el-button text size="small" class="holders-toggle" @click="showHolders = !showHolders">
            <i class="arr" :class="{ open: showHolders }"></i>
            其余 {{ sellHolders.length }} 只持仓暂无卖出信号
          </el-button>
          <div v-show="showHolders" class="holders-list">
            <div v-for="(s, i) in sellHolders" :key="s.code + i" class="holder-row">
              <a class="nm" :href="stockHref(s.code)" target="_blank" rel="noopener">{{ s.name || s.code }}</a>
              <span class="cd">{{ s.code }}</span>
              <span class="flex"></span>
              <span class="h-price">{{ s.last_price ?? '—' }}</span>
              <span class="h-pl" :class="priceCls(s.profit_loss_rate)">{{ s.profit_loss_rate != null ? fmtPct(s.profit_loss_rate) : '—' }}</span>
              <el-button size="small" link type="danger" plain @click="decideSell(s)">决定卖出</el-button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- ═══ 管理区（折叠，不影响第一屏） ═══ -->
    <div class="wr-extra">
      <el-collapse v-model="extraOpen">
        <el-collapse-item name="plans">
          <template #title>
            <span class="extra-title">今日计划 · 管理</span>
            <span v-if="pendingPlans" class="extra-badge">{{ pendingPlans }}</span>
            <span class="extra-hint">改价 / 确认 / 添加 / 删除</span>
          </template>
          <div class="extra-body">
            <div class="extra-tools">
              <span class="block-hint">已确认计划在这里盯「距触发」；今日买入卡上可一键「加入计划」</span>
              <div class="extra-ops">
                <el-radio-group v-model="planFilter" size="small">
                  <el-radio-button value="all">全部</el-radio-button>
                  <el-radio-button value="buy">买入</el-radio-button>
                  <el-radio-button value="sell">卖出</el-radio-button>
                </el-radio-group>
                <el-button v-if="pendingUnconfirmed" size="small" type="primary" plain :loading="confirmingAll" @click="confirmAllPlans">
                  全部确认 ({{ pendingUnconfirmed }})
                </el-button>
                <el-button size="small" type="primary" plain :icon="Plus" @click="openPlanDialog">手动添加计划</el-button>
              </div>
            </div>
            <el-table v-loading="plansLoading" :data="filteredPlans" stripe size="small" class="app-table app-table--compact">
              <el-table-column label="代码" width="90">
                <template #default="{ row }">
                  <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
                </template>
              </el-table-column>
              <el-table-column label="名称" min-width="100">
                <template #default="{ row }">
                  <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
                </template>
              </el-table-column>
              <el-table-column label="方向" width="66">
                <template #default="{ row }">
                  <span :class="row.direction === 'buy' ? 'up' : 'down'">{{ row.direction === 'buy' ? '买入' : '卖出' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="触发价" width="88">
                <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="距触发" width="96">
                <template #default="{ row }">
                  <span v-if="row.direction === 'buy'" :class="planDistCls(row)">{{ planDistText(row) }}</span>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="止损" width="88">
                <template #default="{ row }">{{ row.stop_loss ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="仓位" width="100">
                <template #default="{ row }">{{ positionText(row.position) }}</template>
              </el-table-column>
              <el-table-column v-if="hasPlanHitRate" label="信效" width="96">
                <template #default="{ row }">
                  <span v-if="row.hit_rate != null" class="cand-hit" :class="hitRateCls(row.hit_rate)">信效 {{ row.hit_rate }}%</span>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column prop="sell_condition" label="卖出条件" min-width="130" show-overflow-tooltip />
              <el-table-column label="状态" width="84">
                <template #default="{ row }">
                  <el-tag size="small" :type="planStatusTag(row)">{{ planStatusLabel(row) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="170" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="row.status === 'pending'" size="small" link type="primary" @click="editPlan(row)">改价</el-button>
                  <el-button v-if="row.status === 'pending' && !row.confirmed" size="small" link type="primary" :loading="confirmingPlanId === row.id" @click="confirmPlanWrite(row)">确认</el-button>
                  <el-button v-if="row.status === 'pending'" size="small" link type="danger" @click="removePlan(row)">删除</el-button>
                  <span v-if="row.status !== 'pending'" class="no-op">—</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!plans.length" :image-size="40" description="今日暂无计划：点「生成当日计划」自动装配，或手动添加" />
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <p class="wr-foot">操作提示：买入清单「去交易」可直接下单；卖出评估「决定卖出」会记入今日卖出计划。所有价格触达实时判定，30 秒自动更新。</p>

    <!-- 添加计划弹窗 -->
    <el-dialog v-model="planDialog" title="添加当日计划" width="480px">
      <el-form :model="planForm" label-width="90px">
        <el-form-item label="代码">
          <el-input v-model="planForm.code" placeholder="如 600519" @blur="autoFillPlanQuote" @keyup.enter="autoFillPlanQuote" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="planForm.name" placeholder="可选，自动解析" readonly />
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="planForm.direction">
            <el-radio value="buy">买入</el-radio>
            <el-radio value="sell">卖出</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="触发价">
          <el-input-number v-model="planForm.trigger_price" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="止损位">
          <el-input-number v-model="planForm.stop_loss" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="卖出条件">
          <el-input v-model="planForm.sell_condition" placeholder="如 跌破MA60 / 涨超+5% 减半" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planDialog = false">取消</el-button>
        <el-button type="primary" :loading="creatingPlan" @click="submitPlan">保存</el-button>
      </template>
    </el-dialog>

    <!-- 改价 / 改止损 -->
    <el-dialog v-model="editDialog" title="调整当日计划" width="460px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="标的">
          <span class="edit-target">
            <a :href="stockHref(editTargetCode)" target="_blank" rel="noopener" class="stock-link stock-code">{{ editTargetCode }}</a>
            <a :href="stockHref(editTargetCode)" target="_blank" rel="noopener" class="stock-link">{{ editTargetName }}</a>
          </span>
        </el-form-item>
        <el-form-item label="触发价">
          <el-input-number v-model="editForm.trigger_price" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="止损位">
          <el-input-number v-model="editForm.stop_loss" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="卖出条件">
          <el-input v-model="editForm.sell_condition" placeholder="可留空" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 盘中买入 · 快速交易 -->
    <el-dialog v-model="buyTradeDialog" title="盘中买入 · 快速交易" width="440px">
      <div v-if="buyTradeRow" class="quick-trade">
        <div class="qt-head">
          <a :href="stockHref(buyTradeRow.code)" target="_blank" rel="noopener" class="fav-code stock-link stock-code">{{ buyTradeRow.code }}</a>
          <a :href="stockHref(buyTradeRow.code)" target="_blank" rel="noopener" class="qt-name stock-link">{{ buyTradeRow.name }}</a>
          <el-tag size="small" type="danger">可执行</el-tag>
        </div>
        <p class="qt-advice">{{ buyAdvice(buyTradeRow) }}</p>
        <div class="qt-grid">
          <div class="fld"><span class="k">触发价</span><span class="v">{{ buyTradeRow.trigger_price ?? '—' }}</span></div>
          <div class="fld"><span class="k">实时价</span><span class="v">{{ buyTradeRow.last_price ?? '—' }}</span></div>
        </div>
        <el-form label-width="90px" class="qt-form" @submit.prevent="submitQuickBuy">
          <el-form-item label="买入数量">
            <el-input-number v-model="buyTradeQty" :min="100" :step="100" :precision="0" style="width: 100%" />
          </el-form-item>
          <el-form-item label="预计金额">
            <span class="qt-amount">≈ {{ fmtMoney((buyTradeRow.last_price ?? 0) * buyTradeQty) }} 元</span>
          </el-form-item>
        </el-form>
        <p class="qt-tip">按实时价市价成交；成交后自动标记当日计划「已执行」并从候选移除。</p>
      </div>
      <template #footer>
        <el-button @click="buyTradeDialog = false">取消</el-button>
        <el-button type="primary" :loading="buyTradeLoading" :disabled="!canQuickBuy" @click="submitQuickBuy">确认买入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus } from '@element-plus/icons-vue'
import { warRoomApi } from '@/api/warRoom'
import { paperApi } from '@/api/paper'
import { stocksApi } from '@/api/stocks'
import { subscribeQuotesUpdate, type QuotesUpdateSignal } from '@/utils/quotesSSE'

defineOptions({ name: 'WarRoomHome' })

// ──────────────────────────── 数据状态 ────────────────────────────
const loading = ref(false)
const plansLoading = ref(false)
const guideLoading = ref(false)
const creatingPlan = ref(false)
const macroAutoGenerating = ref(false)
const macro = ref<any>(null)
const reference = ref<any>(null)
const plans = ref<any[]>([])
const guide = ref<any>(null)
const planGen = ref<any>(null)
const genPlanLoading = ref(false)
const genPlanJobId = ref('')
const genPlanProgress = ref(0)
const genPlanStage = ref('')

const todayText = computed(() => {
  const d = new Date()
  const wd = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 周${wd}`
})
const hasPlanHitRate = computed(() => (plans.value || []).some(p => p.hit_rate != null))
const pendingPlans = computed(() => (plans.value || []).filter(p => p.status === 'pending').length)

// 今日操作 · 总览计数（先给全局结论）：买入=可执行，观望=候选中未到位，卖出=有卖出信号
const opsBuy = computed(() => buyList.value.filter((b: any) => buyStatus(b) === 'exec').length)
const opsHold = computed(() => buyList.value.length - opsBuy.value)
const opsSell = computed(() => sellUrgent.value.length)
// 最近一次行情推送时刻（数据新鲜度标注）
const lastQuoteAt = ref('')
const lastUpdateText = computed(() => lastQuoteAt.value ? `更新于 ${lastQuoteAt.value}` : '')
// 计划报价表（SSE 推送填充）：供「今日计划」管理区距触发列盯盘
const planQuoteMap = ref<Record<string, number>>({})
function planDist(row: any): number | null {
  const tp = Number(row.trigger_price)
  const price = planQuoteMap.value[String(row.code)]
  if (!tp || price == null) return null
  return Math.round((price / tp - 1) * 10000) / 100
}
function planDistText(row: any): string {
  const d = planDist(row)
  if (d == null) return '—'
  if (d <= 0) return `已触达 ↓${Math.abs(d)}%`
  return `${d}%`
}
function planDistCls(row: any): string {
  const d = planDist(row)
  if (d == null) return ''
  return d <= 0 ? 'up' : 'down'
}

// fetch 辅助：绕开 axios 拦截器（其 401 刷新 token 逻辑可能挂起）
async function _fetchJSON<T>(path: string, init: RequestInit = {}, timeoutMs = 20000): Promise<T> {
  const token = localStorage.getItem('auth-token') || ''
  const headers = new Headers(init.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(path, { ...init, headers, signal: ctrl.signal })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const j = await res.json()
    return (j as any)?.data ?? j
  } finally {
    clearTimeout(timer)
  }
}
const _planGenerate = () => _fetchJSON<any>('/api/war-room/daily-plan/generate', { method: 'POST', body: '{}' }, 60000)
const _planStatus = (id: string) => _fetchJSON<any>('/api/war-room/daily-plan/status/' + id, {}, 15000)
const _planResult = (id: string) => _fetchJSON<any>('/api/war-room/daily-plan/result/' + id, {}, 15000)

const router = useRouter()

// ──────────────────────────── 大盘方向 ────────────────────────────
const basis = computed(() => macro.value?.basis || null)
const gaugePos = computed(() => {
  const b = basis.value
  if (b?.low_confidence || b?.status === '数据不足' || b?.status === '中性(观望)') return 50
  const score = Number(b?.score ?? 0) || 0
  const norm = Math.max(-1, Math.min(1, score / 10))
  return Math.round(50 + norm * 46)
})
function statusLabel(s?: string): string {
  if (s) return s
  const d = macro.value?.rule?.direction
  if (!d) return '数据不足'
  if (d.includes('多')) return '偏多'
  if (d.includes('空')) return '偏空'
  return '中性(观望)'
}
const macroCls = computed(() => {
  const s = statusLabel(basis.value?.status)
  if (s.includes('空')) return 'bear'
  if (s.includes('多')) return 'bull'
  if (s === '中性(观望)') return 'neutral'
  return 'nodata'
})
const macroAdvice = computed(() => {
  const b = basis.value
  if (!b?.status || b.status === '数据不足') return '数据不足：今日方向不明，谨慎为主'
  if (b.low_confidence || b.status === '中性(观望)') return `置信度 ${b.confidence ?? 0}% 不足 → 观望为主；若操作，仓位减半`
  if (b.status.includes('多')) return '大盘偏多 → 可进取：按计划执行买入，严守止损纪律'
  if (b.status.includes('空')) return '大盘偏空 → 减仓避险为主：暂缓新开仓，执行卖出计划'
  return b.direction || '观望'
})

// ── 规则引擎明细（折叠区）：逐条信号 → 贡献分，可复核总分怎么来的 ──
const signals = computed(() => macro.value?.rule?.signals || [])
const signalOpen = ref(false)
// A 区：指数/期货/情绪等大盘信号（事件行并入 B 区事件卡，不在 A 区重复）
const indexSignals = computed(() =>
  signals.value.filter((s: any) => s.name !== '高重要性政策/数据事件')
)
function fmtSigValue(s: any): string {
  const v = s?.value
  if (v == null) return '—'
  if (typeof v === 'number') return String(Math.round(v * 100) / 100)
  return String(v)
}
// 分值徽章：数值 + 方向色（非零醒目，零弱化）
function sigScore(s: any): number {
  return Number(s?.score ?? 0) || 0
}
function fmtSigScore(s: any): string {
  const sc = sigScore(s)
  return sc > 0 ? `+${sc}` : String(sc)
}
function sigScoreCls(s: any): string {
  const sc = sigScore(s)
  return sc > 0 ? 'up' : sc < 0 ? 'down' : 'flat'
}
// 总分来源分解：如「VIX+1 · 事件-2 · 事件-2」，一眼看到总分怎么凑出来的
const scoreBreakdown = computed(() => {
  const parts = signals.value
    .filter((s: any) => sigScore(s) !== 0)
    .map((s: any) => {
      const name = s.name === '高重要性政策/数据事件' ? '事件' : s.name
      const sc = sigScore(s)
      return `${name}${sc > 0 ? '+' : ''}${sc}`
    })
  return parts.join(' · ')
})
function fmtClock(iso?: string): string {
  if (!iso) return '—'
  let s = String(iso).trim()
  s = s.replace(/\.(\d{3})\d+/, '.$1')
  if (!/([Z]|[+-]\d{2}:?\d{2}( ?\(.+\))?)$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.toDateString() === new Date().toDateString()
    ? `今日 ${hm}`
    : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

// ──────────────────────────── 买入清单 ────────────────────────────
const guideBuys = computed(() => guide.value?.buys || [])
const buyList = computed(() => {
  const list = guideBuys.value.slice()
  list.sort((a: any, b: any) => {
    const ra = rankBuy(a), rb = rankBuy(b)
    if (ra !== rb) return ra - rb
    const da = a.distance_pct == null ? 1e9 : a.distance_pct
    const db = b.distance_pct == null ? 1e9 : b.distance_pct
    return da - db
  })
  return list
})
function rankBuy(b: any): number {
  if (b.triggered && b.confirmed !== false) return 0     // 可执行
  if (b.confirmed === false) return 2                     // 待确认
  return 1                                                // 待回落
}
function buyStatus(b: any): 'exec' | 'wait' | 'confirm' {
  if (b.triggered && b.confirmed !== false) return 'exec'
  if (b.confirmed === false) return 'confirm'
  return 'wait'
}
// 评级徽章四档：可买（红实心）/ 待确认（黄）/ 接近买点（蓝描边）/ 观望（灰）
function buyChipCls(b: any): string {
  const st = buyStatus(b)
  if (st === 'exec') return 'st-exec'
  if (st === 'confirm') return 'st-confirm'
  if (b.distance_pct != null && b.distance_pct <= 2) return 'st-near'
  return 'st-watch'
}
function buyStatusText(b: any): string {
  const st = buyStatus(b)
  if (st === 'exec') return '可买'
  if (st === 'confirm') return '待确认'
  if (b.distance_pct != null && b.distance_pct <= 2) return '接近买点'
  return '观望'
}
function buyAdvice(b: any): string {
  const tp = b.trigger_price
  if (b.triggered && b.confirmed !== false) {
    return tp != null ? `买点成立：已回落至 ${tp} 下方，可以买入` : (b.advice || '买点成立，可以买入')
  }
  if (b.confirmed === false) return '已在候选：到「今日计划」中确认后进入实时提醒'
  if (tp != null && b.distance_pct != null) {
    return `待回落：现价在触发价上方 ${fmtPct(b.distance_pct)}，跌破 ${tp} 时买入`
  }
  return b.advice || '等待触发'
}

// 依据语义标记：按条件文本关键词分类（⚠ 风险/防守 · ✨ 利好/兑现 · · 中性）
// 只做展示层分类，不编造额外依据
function basisCls(t?: string): string {
  const s = (t || '').toString()
  if (/止损|跌破|离场|风险|清仓|破位|预警|下跌|回避/.test(s)) return 'warn'
  if (/止盈|目标|利好|达标|盈利|冲高|突破|买点成立/.test(s)) return 'good'
  return 'flat'
}
function basisIcon(t?: string): string {
  return basisCls(t) === 'warn' ? '⚠' : basisCls(t) === 'good' ? '✨' : '·'
}

// ── 依据编号 · 点击展开明细（每张卡独立展开状态） ──
const reasonOpen = ref<Record<string, boolean>>({})
function rsKey(prefix: string, code?: string, i: number): string {
  return `${prefix}-${code || ''}-${i}`
}
function isReasonOpen(prefix: string, code?: string, i?: number): boolean {
  return i === undefined ? false : !!reasonOpen.value[rsKey(prefix, code, i)]
}
function toggleReasons(prefix: string, code?: string, i?: number) {
  if (i === undefined) return
  const k = rsKey(prefix, code, i)
  reasonOpen.value = { ...reasonOpen.value, [k]: !reasonOpen.value[k] }
}
// 单条依据标记：优先后端 kind（warn/good/flat），缺失时按文本关键词兜底
function reasonCls(r: any): string {
  const k = r?.kind || basisCls(r?.text)
  return k === 'warn' ? 'warn' : k === 'good' ? 'good' : 'flat'
}
function reasonMark(r: any): string {
  return reasonCls(r) === 'warn' ? '⚠' : reasonCls(r) === 'good' ? '✨' : '·'
}
// 依据摘要：⚠2 ✨1 ·1 —— 编号化呈现，一眼看风险/利好配比
function reasonCountText(rs: any[]): string {
  const arr = rs || []
  const w = arr.filter((r: any) => reasonCls(r) === 'warn').length
  const g = arr.filter((r: any) => reasonCls(r) === 'good').length
  const f = arr.length - w - g
  const parts: string[] = []
  if (g) parts.push(`✨${g}`)
  if (w) parts.push(`⚠${w}`)
  if (f) parts.push(`·${f}`)
  return parts.join(' ') || '·0'
}

// ──────────────────────────── 卖出清单 ────────────────────────────
const guideSells = computed(() => guide.value?.sells || [])
const quotesUnavailable = computed(() =>
  !!guide.value && guideSells.value.length > 0 && guideSells.value.every((s: any) => s.last_price == null)
)
function sellLabel(s: any): string {
  const a = (s.advice_label || s.advice || '').toString()
  if (a) return a
  return s.sell_pct != null && s.sell_pct > 0 ? '卖出' : '持有'
}
function sellForce(s: any): number {
  const a = sellLabel(s)
  if (/清仓|止损|S3|离场|无条件/.test(a)) return 0
  if (/减仓|止盈|预警|S1|S2/.test(a)) return 1
  return 2
}
const sellUrgent = computed(() =>
  guideSells.value.filter((s: any) => sellForce(s) < 2)
)
const sellHolders = computed(() =>
  guideSells.value.filter((s: any) => sellForce(s) === 2)
)
const sellList = computed(() => guideSells.value)
function sellCardCls(s: any): 'hard' | 'soft' {
  return sellForce(s) === 0 ? 'hard' : 'soft'
}
function sellStatusText(s: any): string {
  const a = sellLabel(s)
  if (sellForce(s) === 0) return /清仓|无条件|止损/.test(a) ? '清仓' : '卖出'
  if (sellForce(s) === 1) {
    const m = a.match(/(\d+)%/)
    return m ? `减仓 ${m[1]}%` : '止盈'
  }
  return '持有'
}
function sellReason(s: any): string {
  const r = (s.reason || s.advice || '').toString()
  if (r) return r
  return s.sell_pct != null && s.sell_pct > 0
    ? `建议卖出 ${Math.round(s.sell_pct * 100)}% 持仓`
    : '暂无明确的卖出信号，继续持有'
}
// 卖出指令占比：优先后端真实 sell_pct；无数据不猜测，显示 —
function sellPctText(s: any): string {
  if (s.sell_pct != null && s.sell_pct > 0) return `${Math.round(s.sell_pct * 100)}%`
  const m = (sellLabel(s) || '').match(/(\d+)%/)
  if (m) return `${m[1]}%`
  return sellForce(s) === 0 ? '100%' : '—'
}

// 买入候选 → 一键并入今日计划（已确认，进入盘中盯盘）；防重复提交
const addPlanCode = ref('')
async function addBuyToPlan(b: any) {
  const code = String(b.code || '').trim()
  if (!code || addPlanCode.value) return
  addPlanCode.value = code
  try {
    await warRoomApi.createPlan({
      code,
      name: b.name || undefined,
      direction: 'buy',
      trigger_price: b.trigger_price ?? undefined,
      stop_loss: undefined,
      sell_condition: undefined,
      confirmed: true,
    })
    ElMessage.success(`${b.name || code} 已加入今日计划（已确认，价格触达将提醒）`)
    // 与「决定卖出」对称：前端立即从今日买入移除，后端已确认计划不再返回该卡
    if (guide.value?.buys) {
      guide.value.buys = guide.value.buys.filter((x: any) => String(x.code) !== code)
    }
    await loadPlans()
    await loadIntradayGuide()
  } catch (e) {
    ElMessage.error('加入计划失败')
  } finally {
    addPlanCode.value = ''
  }
}

// 卖出决定：并入今日卖出计划（一键，不做多余表单）
async function decideSell(s: any) {
  try {
    await ElMessageBox.confirm(
      `将「${s.name || s.code}」记入今日卖出计划？可稍后在「今日计划」中改价或删除。`,
      '卖出决定', { type: 'warning', confirmButtonText: '决定卖出', cancelButtonText: '再看看' }
    )
  } catch { return }
  try {
    await warRoomApi.createPlan({
      code: String(s.code).trim(),
      name: s.name || undefined,
      direction: 'sell',
      trigger_price: s.trigger_price ?? undefined,
      stop_loss: undefined,
      sell_condition: (s.reason || s.advice || '').slice(0, 120),
      confirmed: true   // 「决定卖出」即确认，不再到「今日计划」二次确认
    })
    ElMessage.success('已记入今日卖出计划（已确认）')
    // 前端立即移除 + 后端同步过滤，30s 刷新后也不会回来
    if (guide.value?.sells) {
      guide.value.sells = guide.value.sells.filter((x: any) => String(x.code) !== String(s.code).trim())
    }
    await loadPlans()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

// ──────────────────────────── 加载 ────────────────────────────
async function loadMacro() {
  loading.value = true
  try {
    const res: any = await warRoomApi.getMacroOverview()
    macro.value = res?.snapshot || null
    macroAutoGenerating.value = !!res?.auto_generating
    if (macroAutoGenerating.value) {
      stopMacroAuto()
      macroAutoTimer = window.setInterval(async () => {
        try {
          const r: any = await warRoomApi.getMacroOverview()
          if (r?.snapshot) {
            macro.value = r.snapshot
            macroAutoGenerating.value = false
            stopMacroAuto()
          }
        } catch { /* 轮询失败忽略，下轮重试 */ }
      }, 15000)
    }
  } catch (e) {
    macro.value = null
  }
  loading.value = false
}
let macroAutoTimer: number | null = null
function stopMacroAuto() { if (macroAutoTimer) { window.clearInterval(macroAutoTimer); macroAutoTimer = null } }

async function loadPlans() {
  plansLoading.value = true
  try {
    const data = await warRoomApi.getPlans()
    plans.value = data?.items || []
  } catch (e) {
    console.warn('[WarRoom] loadPlans', e)
  } finally {
    plansLoading.value = false
  }
}

async function loadIntradayGuide() {
  guideLoading.value = true
  try {
    guide.value = await warRoomApi.getIntradayGuide()
  } catch (e) {
    console.warn('[WarRoom] loadIntradayGuide', e)
  } finally {
    guideLoading.value = false
  }
}

// 重大新闻（参考数据源：快讯多源聚合 + 影响度打分）
async function loadReference() {
  try {
    reference.value = await warRoomApi.getMacroReference()
  } catch (e) {
    console.warn('[WarRoom] loadReference', e)
    if (!reference.value) reference.value = null
  }
}

// 重要事件（重大新闻）：剔除个股类、只留 |影响度| ≥ 50 的强影响事件（与规则引擎计入总分的口径一致），
// 按影响强度 + 重要性排序，强影响在前
const newsList = computed(() => {
  const items = (reference.value?.news_top || []).filter((n: any) =>
    String(n.category) !== '个股' && Math.abs(Number(n.impact_score ?? 0) || 0) >= 50
  )
  const list = items.slice()
  list.sort((a: any, b: any) => {
    const ia = Math.abs(a.impact_score ?? 0)
    const ib = Math.abs(b.impact_score ?? 0)
    if (ia !== ib) return ib - ia
    const wa = a.importance === 'high' ? 0 : a.importance === 'medium' ? 1 : 2
    const wb = b.importance === 'high' ? 0 : b.importance === 'medium' ? 1 : 2
    return wa - wb
  })
  return list
})
// 重要事件区独立折叠（默认展开；配合外层"打分依据"折叠两层可收起）
const newsOpen = ref(true)
// 重要事件（B 区）：直接渲染计入总分的 signals 事件（与总分同源，杜绝加和对不上）
const eventSignals = computed(() =>
  signals.value.filter((s: any) => s.name === '高重要性政策/数据事件')
)
const evLimit = ref(5)
const shownEvents = computed(() => eventSignals.value.slice(0, evLimit.value))
function evDir(s: any): string {
  return Number(s?.score ?? 0) > 0 ? 'bull' : 'bear'
}
function evDirText(s: any): string {
  return Number(s?.score ?? 0) > 0 ? '利多' : '利空'
}
function evLevel(s: any): string {
  const imp = Math.abs(Number(s?.impact_score ?? 0)) || 0
  if (imp >= 60) return '强'
  if (imp >= 30) return '中'
  return Number(s?.score ?? 0) !== 0 ? '强' : '弱'
}
// 事件对应的新闻详情（标题匹配 news_top），补充解读/板块/来源；匹配不到返回 null
function evDetail(s: any): any {
  if (!s?.title) return null
  const t = String(s.title).trim()
  return newsList.value.find((n: any) => String(n.title || '').trim() === t) || null
}
// 事件打分制：直接显示对总分的贡献（±3 重大 / ±2 重要），与规则引擎分档一致
function evScoreText(s: any): string {
  const c = Number(s?.score ?? 0)
  if (!c) return '—'
  return c > 0 ? `+${c}` : String(c)
}
function evScoreCls(s: any): string {
  const c = Number(s?.score ?? 0)
  if (!c) return 'is-na'
  return c > 0 ? 'up' : 'down'
}
function newsTime(t?: string): string {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function sourceShort(src?: string): string {
  if (!src) return ''
  const s = String(src)
  if (s.startsWith('资讯雷达')) return '资讯雷达'
  return s.length > 8 ? s.slice(0, 8) : s
}
function importanceTag(v?: string): 'danger' | 'warning' | 'info' {
  if (v === 'high' || v === '高') return 'danger'
  if (v === 'medium' || v === '中') return 'warning'
  return 'info'
}

async function refreshCurrent() {
  loading.value = true
  await Promise.allSettled([loadMacro(), loadPlans(), loadIntradayGuide(), loadReference()])
  loading.value = false
}

// ──────────────────────────── 盘中实时（SSE + 30s 轮询） ────────────────────────────
let stopQuotes: (() => void) | null = null
let intradayPoll: number | null = null
const liveOn = ref(false)

function onQuotesUpdate(signal: QuotesUpdateSignal) {
  const qs = signal.quotes
  if (!qs) return
  if (Object.keys(qs).length) {
    liveOn.value = true
    lastQuoteAt.value = fmtClock(new Date().toISOString())
  }
  // 兜底：SSE 推送的实时价同时写入计划报价表，供「今日计划」管理区距触发列盯盘
  const nextMap = { ...planQuoteMap.value }
  let changed = false
  for (const k of Object.keys(qs)) {
    const close = qs[k]?.close
    if (close != null && nextMap[k] !== close) { nextMap[k] = close; changed = true }
  }
  if (changed) planQuoteMap.value = nextMap
  if (guide.value?.buys) {
    guide.value.buys = guide.value.buys.map((p: any) => {
      const q = qs[p.code]
      if (!q || q.close == null) return p
      const tp = p.trigger_price
      const price = q.close
      const dist = tp ? Math.round((price / tp - 1) * 10000) / 100 : null
      const triggered = tp != null && price <= tp
      return {
        ...p,
        last_price: price,
        distance_pct: dist,
        triggered: !!triggered,
        advice: triggered
          ? `已回落至 ${tp} 下方，时间点成立，可执行买入`
          : (dist != null && dist <= 2 ? `接近触发价（距触发价 ${dist}%），可提前挂单` : p.advice)
      }
    })
  }
  if (guide.value?.sells) {
    guide.value.sells = guide.value.sells.map((p: any) => {
      const q = qs[p.code]
      if (!q || q.close == null) return p
      const price = q.close
      const cost = p.avg_cost
      const stop = p.stop_loss_price
      const take = p.take_profit_price
      let advice = p.advice
      let adviceLabel = p.advice_label
      let reason = p.reason
      if (stop && price <= Number(stop)) {
        advice = '触发止损'
        adviceLabel = '无条件离场'
        reason = `现价 ${price} 已跌破止损位 ${stop}，无条件止损离场`
      } else if (take && price >= Number(take) && !/持有/.test(advice || '')) {
        advice = '触及止盈'
        adviceLabel = '分批止盈'
        reason = `现价 ${price} 已达止盈位 ${take}，分批止盈一半`
      }
      return {
        ...p,
        last_price: price,
        profit_loss_rate: cost ? Math.round((price / cost - 1) * 10000) / 100 : null,
        advice, advice_label: adviceLabel, reason
      }
    })
  }
}

function startIntradayLive() {
  stopIntradayLive()
  stopQuotes = subscribeQuotesUpdate(onQuotesUpdate, () => {})
  intradayPoll = window.setInterval(() => { loadIntradayGuide() }, 30000)
}
function stopIntradayLive() {
  if (stopQuotes) { stopQuotes(); stopQuotes = null }
  if (intradayPoll) { window.clearInterval(intradayPoll); intradayPoll = null }
}

// ──────────────────────────── 操作 ────────────────────────────
function stockHref(code?: string): string {
  if (!code) return ''
  return `/stocks/${code}`
}
function goScheduled() { router.push('/tasks') }
function positionText(p: any): string {
  if (!p) return '—'
  if (p.shares) return `${p.shares}股 (${fmtPct(p.ratio * 100, 0)})`
  if (p.ratio) return fmtPct(p.ratio * 100, 0)
  return JSON.stringify(p)
}
function hitRateCls(hit: number | null | undefined): string {
  if (hit == null) return ''
  return hit >= 60 ? 'hit-good' : 'hit-low'
}
function planStatusLabel(row: any): string {
  const s = row.status
  if (s === 'pending') return row.confirmed ? '已确认' : '待确认'
  return { executed: '已执行', cancelled: '已取消' }[s] || s
}
function planStatusTag(row: any): 'success' | 'warning' | 'info' {
  const s = row.status
  if (s === 'pending') return row.confirmed ? 'success' : 'warning'
  return ({ executed: 'success', cancelled: 'info' } as any)[s] || 'info'
}
function priceCls(v: unknown): string {
  if (v == null || Number.isNaN(Number(v)) || Number(v) === 0) return ''
  return Number(v) > 0 ? 'up' : 'down'
}
function distCls(v: unknown): string {
  // 距触发价：负值/0 = 已回落到位（买点成立，红）；正值 = 还没到（绿）
  if (v == null || Number.isNaN(Number(v))) return ''
  return Number(v) <= 0 ? 'up' : 'down'
}
function fmtPct(v: unknown, digits = 2): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}
function fmtMoney(v: unknown, currency = '¥', digits = 2): string {
  const n = Number(v)
  if (v == null || Number.isNaN(n)) return '—'
  return `${currency}${n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

// 计划生成（异步 job + 轮询）：产出候选自动并入「今日买入」
let planCompletionTimer: ReturnType<typeof setInterval> | null = null
function _clearPlanWatchdog() {
  if (planCompletionTimer) { clearInterval(planCompletionTimer); planCompletionTimer = null }
}

// 自动补生成当日计划（去除"生成当日计划"按钮的操作层）：
// 打开页面/刷新时，若今日快照未生成且买入清单为空 → 自动后台生成一次（会话级去重），
// 生成后候选自动出现在「今日买入」，无需任何点击。
let planAutoTriggered = false
async function ensurePlanAuto() {
  if (planAutoTriggered || genPlanLoading.value) return
  if (buyList.value.length) return          // 已有候选/计划，无需生成
  planAutoTriggered = true
  try {
    const tp = await warRoomApi.getTodayPlan()
    if (tp?.generated) return               // 快照已生成，直接读即可（本轮逻辑已加载）
  } catch { /* 查询失败仍尝试自动生成 */ }
  await generatePlan()
}

async function generatePlan() {
  if (genPlanLoading.value) return
  _clearPlanWatchdog()
  genPlanLoading.value = true
  planGen.value = null
  genPlanJobId.value = ''
  genPlanProgress.value = 0
  genPlanStage.value = '环境'
  try {
    const job = await _planGenerate()
    if (!job?.job_id) {
      ElMessage.error('计划生成失败')
      genPlanLoading.value = false
      return
    }
    const jobId = job.job_id
    genPlanJobId.value = jobId
    const deadline = Date.now() + 180000
    let done = false
    let failCount = 0
    while (!done && Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 300))
      try {
        const st = await _planStatus(jobId)
        if (!st) continue
        if (st.progress != null) genPlanProgress.value = st.progress
        if (st.stage) genPlanStage.value = st.stage
        if (st.status === 'done') {
          const result = await _planResult(jobId)
          if (result) {
            planGen.value = result
            genPlanProgress.value = 100
            ElMessage.success(`已生成 ${result.candidates_count ?? 0} 条计划候选，已并入「今日买入」`)
          } else {
            ElMessage.success('当日计划已生成')
          }
          genPlanJobId.value = ''
          done = true
        } else if (st.status === 'error') {
          ElMessage.error(st.error || '计划生成失败')
          done = true
        }
      } catch {
        if (++failCount >= 5) { ElMessage.error('计划状态获取失败，请重试'); done = true }
      }
    }
    if (!done) {
      ElMessage.warning('生成仍在后台进行，完成后会自动保存并出现在「今日买入」，可稍后刷新')
    }
    genPlanLoading.value = false
    await loadIntradayGuide()
    await loadPlans()
  } catch (e) {
    ElMessage.error('计划生成失败')
  } finally {
    genPlanLoading.value = false
    genPlanJobId.value = ''
    _clearPlanWatchdog()
  }
}

// 手动添加 / 改价 / 确认 / 删除 计划
const planDialog = ref(false)
const planForm = ref({ code: '', name: '', direction: 'buy', trigger_price: undefined as number | undefined, stop_loss: undefined as number | undefined, sell_condition: '' })
function openPlanDialog() {
  planForm.value = { code: '', name: '', direction: 'buy', trigger_price: undefined, stop_loss: undefined, sell_condition: '' }
  planDialog.value = true
}
// 手动添加计划：输入A股代码后自动带出名称，并以现价为触发价默认值
async function autoFillPlanQuote() {
  const code = String(planForm.value.code || '').trim()
  if (!/^\d{6}$/.test(code)) return
  try {
    const res = await stocksApi.getQuote(code)
    const data = res?.data
    if (!data) return
    if (data.name && !planForm.value.name) planForm.value.name = data.name
    const px = Number(data.price)
    if (!Number.isNaN(px) && px > 0 && planForm.value.trigger_price == null) {
      planForm.value.trigger_price = px
    }
  } catch (e) {
    // 行情获取失败则保持原状，不阻断用户手动填写
  }
}
async function submitPlan() {
  if (!planForm.value.code.trim()) { ElMessage.warning('请填写代码'); return }
  creatingPlan.value = true
  try {
    await warRoomApi.createPlan({
      code: planForm.value.code.trim(),
      name: planForm.value.name || undefined,
      direction: planForm.value.direction,
      trigger_price: planForm.value.trigger_price,
      stop_loss: planForm.value.stop_loss,
      sell_condition: planForm.value.sell_condition || undefined,
      confirmed: true
    })
    ElMessage.success('计划已保存')
    planDialog.value = false
    await loadPlans()
    await loadIntradayGuide()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    creatingPlan.value = false
  }
}

const editDialog = ref(false)
const editTargetId = ref('')
const editTargetCode = ref('')
const editTargetName = ref('')
const savingEdit = ref(false)
const editForm = ref({ trigger_price: undefined as number | undefined, stop_loss: undefined as number | undefined, sell_condition: '' })
function editPlan(row: any) {
  editTargetId.value = row.id
  editTargetCode.value = row.code
  editTargetName.value = row.name || row.code
  editForm.value = {
    trigger_price: row.trigger_price ?? undefined,
    stop_loss: row.stop_loss ?? undefined,
    sell_condition: row.sell_condition || ''
  }
  editDialog.value = true
}
async function saveEdit() {
  savingEdit.value = true
  try {
    const payload: Record<string, any> = {}
    if (editForm.value.trigger_price != null) payload.trigger_price = editForm.value.trigger_price
    if (editForm.value.stop_loss != null) payload.stop_loss = editForm.value.stop_loss
    if (editForm.value.sell_condition) payload.sell_condition = editForm.value.sell_condition
    await warRoomApi.updatePlanDetail(editTargetId.value, payload)
    await loadPlans()
    await loadIntradayGuide()
    ElMessage.success('已更新')
    editDialog.value = false
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingEdit.value = false
  }
}

const confirmingPlanId = ref('')
async function confirmPlanWrite(row: any) {
  if (row.status !== 'pending' || row.confirmed) return
  confirmingPlanId.value = row.id
  try {
    await warRoomApi.updatePlanDetail(row.id, { confirmed: true })
    ElMessage.success(`${row.name || row.code} 已确认，盘中价格触达将提醒`)
    await loadPlans()
    await loadIntradayGuide()
  } catch (e) {
    ElMessage.error('确认失败')
  } finally {
    confirmingPlanId.value = ''
  }
}

// 今日计划 · 按方向筛选 + 一键全部确认
const planFilter = ref<'all' | 'buy' | 'sell'>('all')
const filteredPlans = computed(() => {
  if (planFilter.value === 'all') return plans.value
  return plans.value.filter((p: any) => p.direction === planFilter.value)
})
const pendingUnconfirmed = computed(() =>
  plans.value.filter((p: any) => p.status === 'pending' && !p.confirmed).length
)
const confirmingAll = ref(false)
async function confirmAllPlans() {
  const targets = plans.value.filter((p: any) => p.status === 'pending' && !p.confirmed)
  if (!targets.length) return
  confirmingAll.value = true
  try {
    const results = await Promise.allSettled(
      targets.map((p: any) => warRoomApi.updatePlanDetail(p.id, { confirmed: true }))
    )
    const ok = results.filter(r => r.status === 'fulfilled').length
    ElMessage.success(`已确认 ${ok}/${targets.length} 条计划，进入盘中盯盘`)
    await loadPlans()
    await loadIntradayGuide()
  } catch (e) {
    ElMessage.error('批量确认失败')
  } finally {
    confirmingAll.value = false
  }
}
async function removePlan(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除计划「${row.name || row.code}」？`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await warRoomApi.deletePlan(row.id)
    ElMessage.success('计划已删除')
    await loadPlans()
    await loadIntradayGuide()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// 盘中买入：快速交易（成交后自动关联计划、从候选移除）
const buyTradeDialog = ref(false)
const buyTradeRow = ref<any>(null)
const buyTradeQty = ref(100)
const buyTradeLoading = ref(false)
const canQuickBuy = computed(() => !!buyTradeRow.value?.triggered && buyTradeQty.value > 0)
function goTrade(row: any) {
  buyTradeRow.value = row
  buyTradeQty.value = 100
  buyTradeDialog.value = true
}
async function submitQuickBuy() {
  const row = buyTradeRow.value
  if (!row || !canQuickBuy.value) return
  buyTradeLoading.value = true
  try {
    await paperApi.placeOrder({
      code: row.code,
      side: 'buy',
      quantity: buyTradeQty.value,
      stock_name: row.name,
      analysis_id: row.plan_id || undefined,
    })
    ElMessage.success(`${row.name || row.code} 买入成交`)
    buyTradeDialog.value = false
    // 候选类标的（无 plan_id）成交后直接否决候选，避免清单内重复提示
    if (!row.plan_id && row.code) {
      try {
        await _fetchJSON('/api/war-room/daily-plan/dismiss', {
          method: 'POST',
          body: JSON.stringify({ code: String(row.code).trim(), kind: 'candidate', dismissed: true }),
        }, 10000)
      } catch { /* 持久化失败不阻塞 */ }
    }
    await loadIntradayGuide()
    await loadPlans()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '买入失败，请检查模拟账户资金是否充足')
  } finally {
    buyTradeLoading.value = false
  }
}

// 折叠管理区
const extraOpen = ref<string[]>([])
const showHolders = ref(false)

onMounted(async () => {
  await Promise.allSettled([loadMacro(), loadPlans(), loadIntradayGuide(), loadReference()])
  startIntradayLive()
  // 打开页面即自动补生成当日计划（缺快照且空态时），无需手动点击
  ensurePlanAuto()
})
onActivated(() => {
  genPlanLoading.value = false
  genPlanJobId.value = ''
  genPlanProgress.value = 0
  genPlanStage.value = ''
  planGen.value = null
  _clearPlanWatchdog()
  refreshCurrent()
  startIntradayLive()
})
onDeactivated(() => stopIntradayLive())
onUnmounted(() => {
  stopIntradayLive()
  stopMacroAuto()
  _clearPlanWatchdog()
})
</script>

<style lang="scss" scoped>
.war-room {
  font-variant-numeric: tabular-nums;

  .up { color: var(--app-up); }    // A股惯例：涨 = 红
  .down { color: var(--app-down); } // 跌 = 绿
  .flex { flex: 1; }
  .no-op { color: var(--el-text-color-placeholder); }

  // ═══ 顶栏 ═══
  .wr-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 12px;

    .wr-head {
      display: flex;
      align-items: baseline;
      gap: 12px;
      .wr-title { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: 1px; color: var(--el-text-color-primary); }
      .wr-date { font-size: 13px; color: var(--el-text-color-secondary); }
    }
    .wr-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      .live {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--el-text-color-placeholder);
        .live-dot {
          width: 8px; height: 8px; border-radius: 50%;
          background: var(--el-text-color-placeholder);
        }
        &.on {
          color: var(--el-color-primary);
          .live-dot {
            background: var(--el-color-primary);
            animation: pulse 1.8s ease-in-out infinite;
          }
        }
      }
    }
  }

  // ═══ 大盘方向条 ═══
  .macro-bar {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    padding: 12px 18px;
    margin-bottom: 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-left: 4px solid var(--el-text-color-placeholder);
    border-radius: 12px;
    background: var(--el-bg-color);

    &.bull { border-left-color: var(--el-color-danger); }
    &.bear { border-left-color: var(--el-color-success); }
    &.neutral { border-left-color: var(--el-color-warning); }
    &.nodata { border-left-color: var(--el-text-color-placeholder); }

    .macro-main {
      display: flex;
      align-items: center;
      gap: 10px;
      .macro-pill {
        font-style: normal;
        font-size: 18px;
        font-weight: 800;
        color: var(--el-color-primary);
      }
      &.bull .macro-pill { color: var(--el-color-danger); }
      &.bear .macro-pill { color: var(--el-color-success); }
      &.neutral .macro-pill { color: var(--el-color-warning); }
      &.nodata .macro-pill { color: var(--el-text-color-secondary); }
      .macro-conf { font-size: 13px; color: var(--el-text-color-secondary); b { font-size: 15px; color: var(--el-text-color-primary); } }
    }
    .macro-advice { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
    .macro-gauge {
      position: relative;
      display: flex;
      width: 240px;
      height: 18px;
      margin-left: auto;
      border-radius: 99px;
      overflow: visible;
      .g-seg {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: #fff;
        // 用显式类而非 :first/:last-child —— gauge 内还有 g-needle，:last-child 会失效导致白字白底
        &.bear { border-radius: 99px 0 0 99px; background: var(--el-color-success); }
        &.neu { background: var(--el-color-info); }
        &.bull { border-radius: 0 99px 99px 0; background: var(--el-color-danger); }
      }
      .g-needle {
        position: absolute;
        top: -4px;
        width: 3px;
        height: 26px;
        background: var(--el-color-primary);
        border-radius: 2px;
        transform: translateX(-50%);
        transition: left .6s cubic-bezier(.2, .8, .2, 1);
        box-shadow: 0 0 4px rgba(0, 0, 0, .25);
        &:after {
          content: '';
          position: absolute;
          bottom: -3px; left: 50%;
          transform: translateX(-50%);
          border-left: 4px solid transparent;
          border-right: 4px solid transparent;
          border-top: 5px solid var(--el-color-primary);
        }
      }
    }
    .macro-meta { font-size: 12px; color: var(--el-text-color-placeholder); }

    // 打分依据 · 折叠（融合进方向条，非独立卡片）
    .macro-facts {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      margin-top: 4px;
      padding: 6px 10px;
      border: 1px dashed var(--el-border-color-lighter);
      border-radius: 8px;
      cursor: pointer;
      user-select: none;
      transition: background .2s, border-color .2s;
      &:hover { background: var(--el-fill-color-lighter); border-color: var(--el-border-color-hover); }

      .mf-label { font-size: 12px; font-weight: 700; color: var(--el-text-color-primary); }
      .mf-sum {
        font-size: 12px; color: var(--el-text-color-secondary);
        b { color: var(--el-color-primary); font-weight: 700; font-size: 14px; }
        .mf-brk { margin-left: 4px; font-style: normal; color: var(--el-text-color-placeholder); }
        .mf-th { margin: 0 4px 0 8px; font-style: normal; color: var(--el-text-color-placeholder); }
      }
      .mf-arrow {
        width: 0; height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid var(--el-text-color-secondary);
        transition: transform .2s;
        &.open { transform: rotate(180deg); }
      }
    }

    .ms-list {
      width: 100%;
      border-top: 1px dashed var(--el-border-color-lighter);
      margin-top: 6px;
      padding-top: 4px;
      animation: riseIn .25s cubic-bezier(.2, .8, .2, 1) both;

      .ms-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 5px 4px;
        font-size: 12.5px;
        border-bottom: 1px dashed var(--el-border-color-lighter);
        border-radius: 6px;
        &:last-child { border-bottom: none; }
        // 有实际贡献分（非零）的行：浅方向色底强调（用 element 官方 light-9，兼容性稳定）
        &.hot { padding: 5px 4px 5px 6px; background: var(--el-fill-color-light); }
        &.hot.score-up { background: var(--el-color-danger-light-9); }
        &.hot.score-down { background: var(--el-color-success-light-9); }

        .ms-name { width: 150px; flex: none; font-weight: 600; color: var(--el-text-color-primary); }
        .ms-val { width: 90px; flex: none; color: var(--el-text-color-regular); font-variant-numeric: tabular-nums; }
        // 分值徽章：非零方向色实底白字（高分对比，避免红字红底看不清），零灰弱化
        .ms-score {
          flex: none;
          width: 34px;
          text-align: center;
          font-size: 13px;
          font-weight: 800;
          font-variant-numeric: tabular-nums;
          line-height: 1.8;
          border-radius: 6px;
          &.up { color: #fff; background: var(--el-color-danger-dark-2); }
          &.down { color: #fff; background: var(--el-color-success-dark-2); }
          &.flat { color: var(--el-text-color-placeholder); background: var(--el-fill-color-light); }
        }
        .ms-detail { flex: 1; min-width: 0; color: var(--el-text-color-secondary); }

        // 事件原文链接：hover 变主题色 + 下划线，整条 detail 可点
        .ms-origin {
          color: inherit;
          text-decoration: none;
          &:hover { color: var(--el-color-primary); text-decoration: underline; }
        }
      }
    }
  }

  // ═══ 今日操作 · 总览条 ═══
  .ops-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 18px;
    margin-bottom: 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 12px;
    background: var(--el-bg-color);
    animation: riseIn .35s cubic-bezier(.2, .8, .2, 1) both;

    .ops-label { font-size: 12px; color: var(--el-text-color-secondary); }
    .ops-count {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 15px;
      font-weight: 800;
      padding: 4px 12px;
      border-radius: 99px;
      i { width: 8px; height: 8px; border-radius: 50%; }
      &.is-buy { color: var(--el-color-danger); background: var(--el-color-danger-light-9); i { background: var(--el-color-danger); } }
      &.is-sell { color: var(--el-color-success); background: var(--el-color-success-light-9); i { background: var(--el-color-success); } }
      &.is-hold { color: var(--el-color-warning-dark-2); background: var(--el-color-warning-light-9); i { background: var(--el-color-warning); } }
    }
    .ops-time { font-size: 12px; color: var(--el-text-color-placeholder); }
  }

  // ═══ 双栏决策板 ═══
  .wr-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    align-items: start;

    @media (max-width: 1100px) {
      grid-template-columns: 1fr;
    }
  }

  .zone {
    background: var(--el-bg-color);
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 12px;
    padding: 14px;

    &.zone-buy { border-top: 3px solid var(--el-color-danger); }
    &.zone-sell { border-top: 3px solid var(--el-color-success); }

    .zone-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
      .zh-left {
        display: flex;
        align-items: baseline;
        gap: 10px;
        h3 {
          margin: 0;
          font-size: 17px;
          font-weight: 800;
          color: var(--el-text-color-primary);
          // 重大新闻副标题：融合进主标题行内，去术语化
          .zone-sub {
            margin-left: 8px;
            font-size: 12px;
            font-weight: 400;
            color: var(--el-text-color-secondary);
          }
        }
        .zone-sub { font-size: 12px; color: var(--el-text-color-secondary); }
      }
      .zone-count {
        min-width: 26px;
        text-align: center;
        font-size: 13px;
        font-weight: 700;
        padding: 3px 9px;
        border-radius: 99px;
        color: var(--el-text-color-secondary);
        background: var(--el-fill-color-light);
      }
    }

    .zone-alert { margin-bottom: 10px; }

    // ── 卡片 ──
    .cards { display: flex; flex-direction: column; gap: 10px; }
    .card {
      padding: 12px 14px;
      border: 1px solid var(--el-border-color-lighter);
      border-left: 4px solid var(--el-border-color);
      border-radius: 10px;
      background: var(--el-bg-color-page);
      transition: border-color .2s, transform .2s;
      animation: riseIn .35s cubic-bezier(.2, .8, .2, 1) both;

      &:hover { border-color: var(--el-border-color-hover); transform: translateY(-1px); }

      &.st-exec, &.hard { border-left-width: 5px; border-left-color: var(--el-color-danger); }
      &.st-wait { border-left-color: var(--el-color-info); }
      &.st-confirm { border-left-color: var(--el-color-warning); }
      &.soft { border-left-color: var(--el-color-warning); }

      .card-top {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
        .nm { font-size: 15px; font-weight: 700; color: var(--el-text-color-primary); text-decoration: none; &:hover { color: var(--el-color-primary); } }
        .cd { font-size: 12px; color: var(--el-text-color-secondary); }
        .tag {
          font-size: 11px;
          padding: 1px 7px;
          border-radius: 99px;
          color: var(--el-color-primary);
          background: var(--el-color-primary-light-9);
          border: 1px solid var(--el-color-primary-light-7);
        }
        .chip {
          font-style: normal;
          font-size: 12px;
          font-weight: 700;
          padding: 2px 9px;
          border-radius: 99px;
          &.st-exec, &.hard { color: #fff; background: var(--el-color-danger); }
          &.st-wait { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
          &.st-watch { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
          &.st-near { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border: 1px solid var(--el-color-primary-light-7); }
          &.st-confirm { color: var(--el-color-warning); background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-7); }
          &.soft { color: var(--el-color-warning-dark-2); background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-7); }
        }
      }

      .num-row {
        display: flex;
        gap: 26px;
        margin-bottom: 6px;
        .num {
          display: flex;
          flex-direction: column;
          gap: 2px;
          k { font-size: 11px; color: var(--el-text-color-placeholder); }
          b { font-size: 16px; font-weight: 700; color: var(--el-text-color-primary); }
        }
      }

      .buy-reason {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 6px;
        font-size: 12px;
        line-height: 1.5;
        color: var(--el-text-color-secondary);
      }

      // 依据标签（买入理由 / 依据条共用）
      .rs-label {
        flex: none;
        font-size: 11px;
        font-weight: 700;
        line-height: 1.6;
        color: var(--el-color-primary);
        background: var(--el-color-primary-light-9);
        border: 1px solid var(--el-color-primary-light-7);
        border-radius: 99px;
        padding: 0 7px;
      }

      // 依据编号条 · 点击展开
      .rs-bar {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 8px;
        padding: 5px 10px;
        border: 1px dashed var(--el-border-color-lighter);
        border-radius: 8px;
        cursor: pointer;
        user-select: none;
        transition: background .2s, border-color .2s;
        &:hover { background: var(--el-fill-color-lighter); border-color: var(--el-border-color-hover); }

        .rs-sum { font-size: 12px; font-weight: 700; color: var(--el-text-color-secondary); }
        .rs-arrow {
          width: 0; height: 0;
          border-left: 5px solid transparent;
          border-right: 5px solid transparent;
          border-top: 6px solid var(--el-text-color-secondary);
          transition: transform .2s;
          &.open { transform: rotate(180deg); }
        }
      }

      // 依据明细列表
      .rs-list {
        margin-top: 6px;
        border: 1px solid var(--el-border-color-lighter);
        border-radius: 8px;
        background: var(--el-bg-color-page);
        padding: 4px 10px;
        animation: riseIn .25s cubic-bezier(.2, .8, .2, 1) both;

        .rs-item {
          display: flex;
          align-items: baseline;
          gap: 6px;
          padding: 5px 0;
          font-size: 12.5px;
          line-height: 1.5;
          color: var(--el-text-color-regular);
          border-bottom: 1px dashed var(--el-border-color-lighter);
          &:last-child { border-bottom: none; }
        }
      }

      .cond {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
        font-size: 13px;
        line-height: 1.55;
        color: var(--el-text-color-regular);
        background: var(--el-fill-color-lighter);
        border-radius: 8px;
        padding: 6px 10px;

        // 依据语义标记：⚠ 风险/防守 · ✨ 利好/兑现 · · 中性
        .basis-mark {
          font-style: normal;
          font-weight: 700;
          &.warn { color: var(--el-color-danger); }
          &.good { color: var(--el-color-success); }
          &.flat { color: var(--el-text-color-placeholder); }
        }

        // 卖出指令行：卖 X% · 触发价 · 原因
        &.act {
          .act-pct { font-weight: 800; color: var(--el-color-danger); }
          .act-trigger { font-size: 12px; color: var(--el-text-color-secondary); }
          .act-reason { flex: 1; min-width: 140px; }
        }
      }
    }

    // ── 空态 ──
    .zone-empty {
      padding: 26px 0;
      text-align: center;
      .ze-t { margin: 0 0 6px; font-size: 14px; font-weight: 700; color: var(--el-text-color-secondary); }
      .ze-s { margin: 0 0 12px; font-size: 12px; color: var(--el-text-color-placeholder); }
    }

    // ── 持有折叠 ──
    .holders {
      margin-top: 12px;
      border-top: 1px dashed var(--el-border-color-lighter);
      padding-top: 8px;
      .holders-toggle { color: var(--el-text-color-secondary); }
      .arr {
        display: inline-block;
        width: 0; height: 0;
        margin-right: 4px;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid var(--el-text-color-secondary);
        transition: transform .2s;
        &.open { transform: rotate(180deg); }
      }
      .holders-list {
        display: flex;
        flex-direction: column;
        .holder-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 7px 6px;
          font-size: 13px;
          border-bottom: 1px solid var(--el-border-color-lighter);
          &:last-child { border-bottom: none; }
          .nm { color: var(--el-text-color-primary); text-decoration: none; }
          .cd { color: var(--el-text-color-secondary); }
          .h-price { color: var(--el-text-color-primary); }
          .h-pl { font-weight: 700; }
        }
      }
    }
  }

  // ═══ 重要事件（重大新闻 topN 融合为事件卡 · ms-news） ═══
  .ms-news {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px dashed var(--el-border-color-lighter);

    .ms-news-head {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      cursor: pointer;
      user-select: none;
      border-radius: 6px;
      transition: background .2s;
      &:hover { background: var(--el-fill-color-lighter); }

      .mf-arrow {
        flex: none;
        width: 0; height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid var(--el-text-color-secondary);
        transition: transform .2s;
        &.open { transform: rotate(180deg); }
      }
      .ms-news-title { font-size: 14px; font-weight: 800; color: var(--el-text-color-primary); }
      .ms-news-sub { margin-left: 8px; font-size: 12px; font-weight: 400; font-style: normal; color: var(--el-text-color-secondary); }
      .ms-news-count { font-size: 12px; color: var(--el-text-color-placeholder); }
    }
    .ms-news-empty { margin: 6px 0; font-size: 13px; color: var(--el-text-color-placeholder); }

    // ── 事件卡：左评分柱 + 右内容（编辑部式） ──
    .ev-cards { display: grid; grid-template-columns: 1fr; gap: 10px; }
    .ev-card {
      display: flex;
      gap: 14px;
      padding: 12px 14px;
      border: 1px solid var(--el-border-color-lighter);
      border-left-width: 4px;
      border-left-style: solid;
      border-radius: 10px;
      background: var(--el-bg-color-page);
      transition: border-color .2s, transform .2s;
      animation: riseIn .35s cubic-bezier(.2, .8, .2, 1) both;

      &:hover { border-color: var(--el-border-color-hover); transform: translateY(-1px); }
      &.bull { border-left-color: var(--el-color-danger); }
      &.bear { border-left-color: var(--el-color-success); }
      &.neutral { border-left-color: var(--el-text-color-placeholder); }

      // 左评分柱
      .ev-side {
        width: 92px;
        flex: none;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 5px;
        padding-top: 2px;

        .ev-dir {
          font-style: normal;
          font-size: 11px;
          font-weight: 700;
          line-height: 1.6;
          padding: 0 10px;
          border-radius: 99px;
          &.bull { color: #fff; background: var(--el-color-danger); }
          &.bear { color: #fff; background: var(--el-color-success); }
          &.neutral { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
        }
        .ev-score {
          // 打分制：显示对总分的贡献（±2/±1），白字深色底高分对比；未计入显示 —
          min-width: 36px;
          text-align: center;
          font-size: 20px;
          font-weight: 800;
          line-height: 1.4;
          border-radius: 6px;
          padding: 0 6px;
          font-variant-numeric: tabular-nums;
          &.up { color: #fff; background: var(--el-color-danger-dark-2); }
          &.down { color: #fff; background: var(--el-color-success-dark-2); }
          &.is-na { color: var(--el-text-color-placeholder); background: var(--el-fill-color-light); font-size: 14px; }
        }
        .ev-lv { font-size: 11px; color: var(--el-text-color-secondary); }
      }

      // 右内容
      .ev-main { flex: 1; min-width: 0; }
      .ev-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 6px;
        .cat-tag { color: var(--el-color-primary); border-color: var(--el-color-primary-light-7); }
        .ev-src { font-size: 12px; color: var(--el-text-color-placeholder); }
      }
      .ev-title {
        margin: 0 0 6px;
        font-size: 14.5px;
        font-weight: 700;
        line-height: 1.5;
        color: var(--el-text-color-primary);

        .ev-origin {
          color: inherit;
          text-decoration: none;
          &:hover { color: var(--el-color-primary); text-decoration: underline; }
        }
      }
      // 解读：方向色左边条 + 淡底（引用样式）
      .ev-analysis {
        margin: 0 0 7px;
        font-size: 13px;
        line-height: 1.6;
        color: var(--el-text-color-regular);
        background: var(--el-fill-color-lighter);
        border-left: 3px solid var(--el-border-color);
        border-radius: 6px;
        padding: 6px 10px;
      }
      &.bull .ev-analysis { border-left-color: var(--el-color-danger-light-5); }
      &.bear .ev-analysis { border-left-color: var(--el-color-success-light-5); }

      .ev-sectors {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
        .sec-label { font-size: 11px; color: var(--el-text-color-placeholder); }
        .sec-chip {
          font-size: 11px;
          padding: 1px 8px;
          border-radius: 99px;
          color: var(--el-color-primary);
          background: var(--el-color-primary-light-9);
          border: 1px solid var(--el-color-primary-light-7);
        }
      }
    }
  }

  // ═══ 管理区 ═══
  .wr-extra {
    margin-top: 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 12px;
    background: var(--el-bg-color);

    .extra-title { font-size: 14px; font-weight: 700; color: var(--el-text-color-primary); }
    .extra-badge {
      margin-left: 8px;
      font-size: 11px;
      font-weight: 700;
      color: var(--el-color-danger);
      background: var(--el-color-danger-light-9);
      padding: 1px 7px;
      border-radius: 99px;
    }
    .extra-hint { margin-left: 10px; font-size: 12px; color: var(--el-text-color-placeholder); }
    .extra-body { padding: 2px 6px 14px; }
    .extra-tools {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 10px;
      .extra-ops { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    }
    .block-hint { font-size: 12px; color: var(--el-text-color-secondary); }
    .cand-hit { font-size: 12px; font-weight: 600; }
    .hit-good { color: var(--el-color-success); }
    .hit-low { color: var(--el-text-color-placeholder); }
  }

  .wr-foot {
    margin: 12px 2px 0;
    font-size: 12px;
    color: var(--el-text-color-placeholder);
  }

  .quick-trade {
    .qt-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
    .qt-name { font-size: 15px; font-weight: 700; text-decoration: none; color: var(--el-text-color-primary); }
    .qt-advice { margin: 0 0 10px; font-size: 13px; color: var(--el-text-color-regular); background: var(--el-fill-color-lighter); padding: 8px 10px; border-radius: 8px; }
    .qt-grid { display: flex; gap: 24px; margin-bottom: 12px; }
    .qt-form { margin-top: 4px; }
    .qt-amount { font-weight: 700; color: var(--el-color-danger); }
    .qt-tip { margin: 4px 0 0; font-size: 12px; color: var(--el-text-color-placeholder); }
  }
}

@keyframes riseIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .3; }
}
</style>