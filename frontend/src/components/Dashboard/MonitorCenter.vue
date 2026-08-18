<template>
  <div class="monitor-center">
    <!-- 工具栏：立即评估 + 刷新 -->
    <div class="monitor-toolbar">
      <el-button type="primary" size="small" :loading="checking" @click="manualCheck">
        <el-icon><Lightning /></el-icon> 立即评估
      </el-button>
      <el-button size="small" :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
      <span class="monitor-tip">交易时间每 60 秒自动评估一次，命中后生成指令 / 触发记录</span>
    </div>

    <!-- 策略流程总览：自选股 → 买入信号 → 模拟持仓 → 卖出信号 → 卖出离场 -->
    <div class="flow-panel">
      <div class="flow-title">
        <el-icon><Connection /></el-icon>
        <span>策略监控流程</span>
        <span class="flow-sub">常用策略命中自动入自选 → 触发买入待确认 → 建仓后监控卖出 → 卖出离场</span>
      </div>
      <div class="flow-track">
        <div class="flow-node">
          <div class="flow-ico watch"><el-icon><Star /></el-icon></div>
          <div class="flow-info">
            <div class="flow-name">自选股</div>
            <div class="flow-num">{{ watchlistCount }}</div>
            <div class="flow-desc">策略命中自动加入</div>
          </div>
        </div>
        <div class="flow-arrow"><span>▶</span></div>

        <div class="flow-node clickable" :class="{ hot: buyPending > 0 }" @click="goOrders">
          <div class="flow-ico buy"><el-icon><ShoppingCart /></el-icon></div>
          <div class="flow-info">
            <div class="flow-name">买入信号</div>
            <div class="flow-num">{{ buyPending }}</div>
            <div class="flow-desc">策略命中 · 待建仓指令</div>
          </div>
        </div>
        <div class="flow-arrow"><span>▶</span></div>

        <div class="flow-node clickable" @click="goOrders">
          <div class="flow-ico pos"><el-icon><Wallet /></el-icon></div>
          <div class="flow-info">
            <div class="flow-name">模拟持仓</div>
            <div class="flow-num">{{ positionCount }}</div>
            <div class="flow-desc">持仓监控卖出信号</div>
          </div>
        </div>
        <div class="flow-arrow"><span>▶</span></div>

        <div class="flow-node clickable" :class="{ hot: sellPending > 0 }" @click="goOrders">
          <div class="flow-ico sell"><el-icon><Sell /></el-icon></div>
          <div class="flow-info">
            <div class="flow-name">卖出信号</div>
            <div class="flow-num">{{ sellPending }}</div>
            <div class="flow-desc">待减仓/清仓指令</div>
          </div>
        </div>
        <div class="flow-arrow"><span>▶</span></div>

        <div class="flow-node dim">
          <div class="flow-ico out"><el-icon><CircleCheck /></el-icon></div>
          <div class="flow-info">
            <div class="flow-name">卖出离场</div>
            <div class="flow-num">—</div>
            <div class="flow-desc">现金回流 · 循环</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 常用策略监控概览 -->
    <div class="strategy-overview">
      <div class="overview-head">
        <div class="overview-title">
          <el-icon><MagicStick /></el-icon>
          <span>常用策略监控</span>
          <span class="overview-sub">在「常用策略」页开启监控开关，命中即自动入自选并生成待确认指令</span>
        </div>
        <el-button size="small" @click="goCommon" text>
          <el-icon><Right /></el-icon> 去配置
        </el-button>
      </div>
      <el-empty v-if="!loading && strategyMonitors.length === 0" description="尚未开启任何策略监控" :image-size="70">
        <p class="empty-hint">前往「常用策略」页，在策略卡片上打开「监控」开关，即可自动跟踪命中股票。</p>
      </el-empty>
      <div v-else class="strategy-chip-grid">
        <div
          v-for="sm in strategyMonitors"
          :key="sm.strategy_id"
          :class="['strategy-chip', { on: sm.enabled }]"
        >
          <div class="chip-ico"><el-icon><component :is="chipIcon(sm.strategy_id)" /></el-icon></div>
          <div class="chip-main">
            <div class="chip-name">{{ sm.name }}</div>
            <div class="chip-desc">{{ sm.enabled ? (strategyHitCount[sm.strategy_id] ?? 0) + ' 只命中待跟踪' : '未开启' }}</div>
          </div>
          <el-switch :model-value="sm.enabled" size="small" :loading="strategyToggling === sm.strategy_id"
            @change="(v) => toggleStrategyMonitor(sm, v)" />
        </div>
      </div>
    </div>

    <!-- 主内容 Tab -->
    <el-tabs v-model="activeTab" class="monitor-tabs">
      <!-- ── 策略指令 ─────────────────────────────────── -->
      <el-tab-pane name="orders">
        <template #label>
          <span class="tab-label">
            <el-icon><Promotion /></el-icon> 策略指令
            <el-badge v-if="pendingOrders.length" :value="pendingOrders.length" :max="99" class="tab-badge" />
          </span>
        </template>

        <el-card class="monitor-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <span>待确认指令</span>
                <el-tag v-if="pendingOrders.length" size="small" type="warning" effect="plain">{{ pendingOrders.length }} 条待处理</el-tag>
              </div>
              <div class="card-actions">
                <el-radio-group v-model="tbsStatusFilter" size="small" @change="loadTbsOrders">
                  <el-radio-button value="pending">待确认</el-radio-button>
                  <el-radio-button value="executed">已执行</el-radio-button>
                  <el-radio-button value="all">全部</el-radio-button>
                </el-radio-group>
              </div>
            </div>
          </template>

          <div v-loading="loadingOrders" class="tbs-body">
            <el-empty
              v-if="!loadingOrders && tbsOrders.length === 0"
              description="暂无待确认指令"
              :image-size="80"
            >
              <p class="empty-hint">
                常用策略命中自动入自选并生成买入指令；建仓后持仓触发离场信号生成卖出指令。点击「立即评估」即时生成指令。
              </p>
            </el-empty>
            <div v-else class="tbs-list">
              <div v-for="o in tbsOrders" :key="o.id" :class="['tbs-item', { done: o.status !== 'pending' }]">
                <div :class="['tbs-dir', o.direction]">{{ o.direction === 'buy' ? '买' : '卖' }}</div>
                <div class="tbs-main">
                  <div class="tbs-top">
                    <span class="tbs-symbol">{{ o.symbol }}</span>
                    <span class="tbs-name">{{ o.name }}</span>
                    <el-tag size="small" :type="o.direction === 'buy' ? 'danger' : 'success'" effect="dark">
                      {{ o.signal_label }}
                    </el-tag>
                    <el-tag size="small" effect="plain" type="info">{{ statusLabel(o.status) }}</el-tag>
                  </div>
                  <div class="tbs-meta">
                    <span>参考价 {{ o.reference_price }}</span>
                    <span>建议仓位 {{ pctLabel(o.position_pct) }}</span>
                    <span>{{ o.rule_name }}</span>
                  </div>
                  <div v-if="o.reason" class="tbs-reason">{{ o.reason }}</div>
                  <div v-if="o.status === 'executed'" class="tbs-result">
                    已成交 {{ o.executed_qty }} 股 @ {{ o.executed_price }}
                  </div>
                </div>
                <div class="tbs-actions" v-if="o.status === 'pending'">
                  <el-button size="small" type="primary" :loading="executingId === o.id" @click="executeOrder(o)">
                    执行
                  </el-button>
                  <el-button size="small" @click="cancelOrder(o)">取消</el-button>
                  <el-button size="small" text @click="dismissOrder(o)">忽略</el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ── 监控规则 ─────────────────────────────────── -->
      <el-tab-pane name="rules">
        <template #label>
          <span class="tab-label">
            <el-icon><List /></el-icon> 监控规则
            <el-tag size="small" type="info" effect="plain" class="tab-count">{{ rules.length }}</el-tag>
          </span>
        </template>

        <el-card class="monitor-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <span>全部规则</span>
                <el-tag size="small" type="info" effect="plain">{{ rules.length }}</el-tag>
              </div>
              <div class="card-actions">
                <el-button size="small" type="primary" @click="openCreate">
                  <el-icon><Plus /></el-icon> 新建规则
                </el-button>
              </div>
            </div>
          </template>

          <div v-loading="loading" class="rules-body">
            <el-empty v-if="!loading && rules.length === 0" description="暂无监控规则" :image-size="80">
              <p class="empty-hint">点击「新建规则」配置信号、价格或市场异动监控。</p>
            </el-empty>
            <div v-else class="rules-list">
              <div v-for="rule in rules" :key="rule.id" class="rule-item" :class="{ disabled: !rule.enabled }">
                <div :class="['rule-status-bar', rule.enabled ? 'on' : 'off']" />
                <div class="rule-main">
                  <div class="rule-top">
                    <el-tag size="small" :type="typeTag(rule.type)" effect="plain">{{ typeLabel(rule.type) }}</el-tag>
                    <span class="rule-name">{{ rule.name || '未命名规则' }}</span>
                    <el-tag v-if="rule.builtin" size="small" type="danger" effect="plain">内置</el-tag>
                    <span v-if="!rule.enabled" class="rule-desc">已停用</span>
                  </div>
                  <div class="rule-meta">
                    <span class="rule-scope">{{ scopeLabel(rule.scope) }}</span>
                    <span v-if="rule.tbs_signals && rule.tbs_signals.length" class="rule-symbols">{{ rule.tbs_signals.join(' / ') }}</span>
                    <span v-else-if="rule.scope === 'symbols'" class="rule-symbols">{{ rule.symbols.join('、') }}</span>
                  </div>
                  <div v-if="rule.conditions && rule.conditions.length" class="rule-conditions">
                    <template v-for="(c, ci) in rule.conditions.slice(0, 3)" :key="ci">
                      <span v-if="ci > 0" class="cond-logic">{{ rule.logic === 'and' ? '且' : '或' }}</span>
                      <span class="cond-item">{{ fieldLabel(c.field) }}{{ c.op === 'truth' ? '' : c.op + (c.value ?? '') }}</span>
                    </template>
                    <span v-if="rule.conditions.length > 3" class="cond-more">+{{ rule.conditions.length - 3 }}</span>
                  </div>
                </div>
                <div class="rule-actions">
                  <el-button size="small" text :title="rule.enabled ? '停用' : '启用'" @click="toggleEnabled(rule)">
                    <el-icon :class="rule.enabled ? 'act-on' : ''"><Lightning /></el-icon>
                  </el-button>
                  <el-button size="small" text @click="openEdit(rule)">
                    <el-icon><EditPen /></el-icon>
                  </el-button>
                  <el-button size="small" text type="danger" :disabled="rule.builtin" :title="rule.builtin ? '内置规则不可删除，可关闭或修改' : '删除'" @click="deleteRule(rule.id)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ── 触发记录 ─────────────────────────────────── -->
      <el-tab-pane name="alerts">
        <template #label>
          <span class="tab-label">
            <el-icon><Bell /></el-icon> 触发记录
            <el-tag v-if="alerts.length" size="small" type="info" effect="plain" class="tab-count">{{ alerts.length }}</el-tag>
          </span>
        </template>

        <div class="monitor-stats">
          <div class="stat-item" :class="{ active: todayCount > 0 }">
            <div class="stat-num">{{ todayCount }}</div>
            <div class="stat-label">今日触发</div>
          </div>
          <div class="stat-item" :class="{ danger: criticalCount > 0 }">
            <div class="stat-num">{{ criticalCount }}</div>
            <div class="stat-label">重要告警</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">{{ enabledRules }}<span class="stat-sub">/{{ rules.length }}</span></div>
            <div class="stat-label">启用规则</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">{{ sourceCounts.signal }}</div>
            <div class="stat-label">信号触发</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">{{ sourceCounts.price }}</div>
            <div class="stat-label">价格/涨跌</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">{{ sourceCounts.market }}</div>
            <div class="stat-label">市场异动</div>
          </div>
        </div>

        <el-card class="monitor-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <span>触发记录</span>
              </div>
              <div class="card-actions">
                <el-radio-group v-model="sourceFilter" size="small" @change="loadAlerts">
                  <el-radio-button value="all">全部</el-radio-button>
                  <el-radio-button value="signal">信号</el-radio-button>
                  <el-radio-button value="price">价格/涨跌</el-radio-button>
                  <el-radio-button value="market">市场异动</el-radio-button>
                </el-radio-group>
                <el-button v-if="alerts.length > 0" size="small" type="danger" text @click="confirmClear">
                  <el-icon><Delete /></el-icon> 清空
                </el-button>
              </div>
            </div>
          </template>

          <div v-loading="loading" class="alerts-body">
            <el-empty v-if="!loading && alerts.length === 0" description="暂无触发记录" :image-size="80">
              <p class="empty-hint">监控规则命中后，触发记录会出现在这里。可在「监控规则」配置规则。</p>
            </el-empty>
            <div v-else class="alerts-list">
              <div v-for="alert in alerts" :key="alert.id" class="alert-item">
                <div :class="['alert-severity-bar', alert.severity || 'info']" />
                <div class="alert-main">
                  <div class="alert-top">
                    <span class="alert-symbol">{{ alert.symbol || '—' }}</span>
                    <span v-if="alert.name" class="alert-name">{{ alert.name }}</span>
                    <span v-if="alert.price != null" class="alert-price" :class="(alert.change_pct ?? 0) >= 0 ? 'up' : 'down'">
                      {{ alert.price }}
                    </span>
                    <span v-if="alert.change_pct != null" class="alert-pct" :class="alert.change_pct >= 0 ? 'up' : 'down'">
                      {{ alert.change_pct >= 0 ? '+' : '' }}{{ alert.change_pct.toFixed(2) }}%
                    </span>
                    <el-tag size="small" :type="severityTag(alert.severity)" effect="plain">
                      {{ sourceLabel(alert.source || alert.rule_type) }}
                    </el-tag>
                  </div>
                  <div class="alert-message">{{ alert.message || '命中监控规则' }}</div>
                  <div v-if="alert.conditions && alert.conditions.length" class="alert-conditions">
                    <span class="cond-label">命中</span>
                    <template v-for="(c, ci) in alert.conditions" :key="ci">
                      <span v-if="ci > 0" class="cond-logic">{{ alert.logic === 'or' ? '或' : '且' }}</span>
                      <span class="cond-item">{{ fieldLabel(c.field) }}{{ c.op === 'truth' ? '' : c.op + (c.value ?? '') }}</span>
                    </template>
                  </div>
                </div>
                <div class="alert-side">
                  <span class="alert-time">{{ formatTs(alert.ts) }}</span>
                  <el-button size="small" text type="danger" @click="deleteAlert(alert.id)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 规则编辑对话框（分步：选择类型 → 配置） -->
    <el-dialog v-model="editorVisible" :title="editingRule ? '编辑监控规则' : '新建监控规则'" width="720px" top="6vh">
      <el-form v-if="editorVisible" label-position="top" class="rule-form">
        <!-- 选择监控类型 -->
        <div class="form-section">
          <div class="form-section-title">1 · 选择监控类型</div>
          <div class="type-grid">
            <div
              v-for="t in typeCards"
              :key="t.key"
              :class="['type-card', { active: draft.type === t.key }]"
              @click="draft.type = t.key"
            >
              <div class="type-ico" :class="t.key"><el-icon><component :is="t.icon" /></el-icon></div>
              <div class="type-name">{{ t.label }}</div>
              <div class="type-desc">{{ t.desc }}</div>
            </div>
          </div>
        </div>

        <!-- 通用配置 -->
        <div class="form-section">
          <div class="form-section-title">2 · 配置规则</div>

            <el-form-item label="规则名称">
              <el-input v-model="draft.name" placeholder="留空使用默认名称" />
            </el-form-item>

            <el-form-item label="作用范围">
              <el-select v-model="draft.scope" style="width: 200px">
                <el-option v-for="s in options.scopes" :key="s.key" :value="s.key" :label="s.label" />
              </el-select>
              <el-select
                v-if="draft.scope === 'symbols'"
                v-model="draft.symbols"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="输入股票代码后回车"
                style="width: 320px; margin-left: 8px;"
              />
              <span v-else-if="draft.scope === 'watchlist'" class="scope-hint">
                <el-icon style="vertical-align: -2px"><InfoFilled /></el-icon>
                自动监控全部自选股，新增自选股自动纳入
              </span>
            </el-form-item>

            <el-form-item label="触发条件">
              <div class="cond-editor">
                <div class="cond-toolbar">
                  <el-select v-model="draft.logic" style="width: 160px">
                    <el-option v-for="l in options.logics" :key="l.key" :value="l.key" :label="l.label" />
                  </el-select>
                  <el-button size="small" @click="addSignalCond">+ 信号条件</el-button>
                  <el-button size="small" @click="addThresholdCond">+ 阈值条件</el-button>
                </div>
                <div v-if="draft.conditions.length === 0" class="cond-empty">点击上方按钮添加触发条件</div>
                <div v-for="(cond, idx) in draft.conditions" :key="idx" class="cond-row">
                  <span class="cond-logic-prefix">{{ condPrefix(idx) }}</span>
                  <el-select v-model="cond.field" style="width: 200px">
                    <template v-if="cond.op === 'truth'">
                      <el-option v-for="f in signalFieldOptions" :key="f.key" :value="f.key" :label="f.label" />
                    </template>
                    <template v-else>
                      <el-option
                        v-for="f in options.threshold_fields"
                        :key="f.key"
                        :value="f.key"
                        :label="f.label"
                        :disabled="!isThresholdFieldAvailable(f.key)"
                      >
                        <el-tooltip
                          v-if="!isThresholdFieldAvailable(f.key)"
                          :content="thresholdFieldTip(f)"
                          placement="left"
                          :show-after="200"
                        >
                          <span>{{ f.label }}</span>
                        </el-tooltip>
                        <template v-else>{{ f.label }}</template>
                      </el-option>
                    </template>
                  </el-select>
                  <el-select v-model="cond.op" style="width: 120px">
                    <el-option v-for="op in condOps(cond)" :key="op" :value="op" :label="opLabel(op)" />
                  </el-select>
                  <el-input-number v-if="cond.op !== 'truth'" v-model="cond.value" :step="0.01" style="width: 140px" />
                  <el-button size="small" text type="danger" @click="removeCond(idx)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </el-form-item>

            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="冷却期(秒)">
                  <el-input-number v-model="draft.cooldown_seconds" :min="0" :step="60" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="严重级别">
                  <el-select v-model="draft.severity" style="width: 100%">
                    <el-option v-for="s in options.severities" :key="s.key" :value="s.key" :label="s.label" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="自定义提示">
                  <el-input v-model="draft.message" placeholder="可留空" />
                </el-form-item>
              </el-col>
            </el-row>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>

    <!-- 立即评估后的待确认指令弹窗 -->
    <el-dialog v-model="pendingVisible" title="待确认指令" width="680px" top="8vh">
      <div v-if="pendingOrders.length === 0" class="pending-empty">暂无待处理指令</div>
      <div v-else class="pending-list">
        <div v-for="o in pendingOrders" :key="o.id" class="pending-item">
          <div :class="['p-dir', o.direction]">{{ o.direction === 'buy' ? '买入' : '卖出' }}</div>
          <div class="p-main">
            <div class="p-top">
              <span class="p-symbol">{{ o.symbol }}</span>
              <span class="p-name">{{ o.name }}</span>
              <el-tag size="small" :type="o.direction === 'buy' ? 'danger' : 'success'" effect="dark">{{ o.signal_label }}</el-tag>
              <el-tag size="small" effect="plain" type="info">{{ o.rule_name }}</el-tag>
            </div>
            <div class="p-reason">{{ o.reason }}</div>
          </div>
          <div class="p-actions">
            <el-button size="small" type="primary" :loading="executingId === o.id" @click="executeOrder(o)">执行</el-button>
            <el-button size="small" @click="cancelOrder(o)">取消</el-button>
            <el-button size="small" text @click="dismissOrder(o)">忽略</el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="pendingVisible = false">关闭</el-button>
        <el-button type="primary" @click="pendingVisible = false; goOrders()">全部查看</el-button>
      </template>
    </el-dialog>

    <!-- 买入执行确认（可调整数量，默认一手） -->
    <el-dialog v-model="execConfirmVisible" title="确认执行买入" width="440px" top="20vh">
      <div v-if="execOrder" style="font-size: 13px;">
        <div style="margin-bottom: 12px;">
          买入 <strong>{{ execOrder.symbol }}</strong>（{{ execOrder.name }}）
          <el-tag size="small" type="danger" effect="dark" style="margin-left: 6px">{{ execOrder.signal_label }}</el-tag>
          <el-tag size="small" effect="plain" type="info" style="margin-left: 6px">{{ execOrder.rule_name }}</el-tag>
        </div>
        <div style="font-size: 12px; color: #909399; margin-bottom: 14px;">
          参考价 {{ execOrder.reference_price }} · 建议仓位 {{ pctLabel(execOrder.position_pct) }}
        </div>
        <el-form label-width="80px">
          <el-form-item label="买入数量">
            <el-input-number v-model="execQty" :min="100" :step="100" />
            <span style="margin-left: 8px; font-size: 12px; color: #909399;">股（A股按 100 股一手）</span>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="execConfirmVisible = false">取消</el-button>
        <el-button type="primary" :loading="executingId === execOrder?.id" @click="doExecute(execOrder!)">确认买入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Lightning, Refresh, Bell, List, Plus, Delete, EditPen, InfoFilled,
  Connection, Star, ShoppingCart, Wallet, Sell, CircleCheck, MagicStick,
  Aim, TrendCharts, FullScreen, Warning, Odometer, Right,
} from '@element-plus/icons-vue'
import {
  monitorApi, genRuleId,
  type MonitorRule, type MonitorAlert, type MonitorCondition, type MonitorOptions, type TbsOrder, type StrategyMonitorStatus,
} from '@/api/monitor'
import { paperApi } from '@/api/paper'
import { favoritesApi } from '@/api/favorites'
import { strategyApi } from '@/api/strategy'

// ── 状态 ────────────────────────────────────────────────
const checking = ref(false)
const loading = ref(false)
const saving = ref(false)
const activeTab = ref<'orders' | 'rules' | 'alerts'>('orders')
const sourceFilter = ref<'all' | 'signal' | 'price' | 'market'>('all')
const alerts = ref<MonitorAlert[]>([])
const rules = ref<MonitorRule[]>([])
const options = reactive<MonitorOptions>({
  threshold_fields: [], signal_fields: [], operators: [],
  types: [], scopes: [], logics: [], severities: [],
})

const editorVisible = ref(false)
const editingRule = ref<MonitorRule | null>(null)
const draft = reactive<{
  id: string; name: string; enabled: boolean; type: string; scope: string;
  symbols: string[]; user_id?: string; conditions: MonitorCondition[]; logic: string;
  cooldown_seconds: number; severity: string; message: string;
}>({
  id: '', name: '', enabled: true, type: 'signal', scope: 'symbols', symbols: [],
  conditions: [], logic: 'and', cooldown_seconds: 3600, severity: 'info', message: '',
})

let pollTimer: number | null = null

// ── 三买三卖待确认指令 ──────────────────────────────────
const tbsOrders = ref<TbsOrder[]>([])
const loadingOrders = ref(false)
const tbsStatusFilter = ref<'pending' | 'executed' | 'all'>('pending')
const executingId = ref<string | null>(null)
const pendingVisible = ref(false)
// 买入执行确认（可调整数量，默认一手）
const execConfirmVisible = ref(false)
const execOrder = ref<TbsOrder | null>(null)
const execQty = ref(100)

// ── 常用策略监控概览 ────────────────────────────────────
const strategyMonitors = ref<StrategyMonitorStatus[]>([])
const strategyHitCount = ref<Record<string, number>>({})
const strategyToggling = ref<string | null>(null)
const strategyIcons: Record<string, any> = {
  ma_golden_cross: TrendCharts, macd_golden: TrendCharts, n_day_high_breakout: Aim,
  n_day_low_reversal: FullScreen, oversold_bounce: Refresh, trend_breakout: TrendCharts,
  boll_breakout: FullScreen, volume_price_surge: TrendCharts, pullback_ma20_bounce: TrendCharts,
  strong_open: Aim, low_volatility_leader: Odometer, low_pe_high_div_leader: Warning,
  turnaround: Refresh, small_cap_value: Odometer,
}
const chipIcon = (id: string) => strategyIcons[id] || MagicStick

const goCommon = () => { window.location.href = '/screening/common' }

const loadStrategyMonitors = async () => {
  try {
    // 并行：监控状态 + 各策略命中数
    const [statusRes, listRes] = await Promise.allSettled([
      monitorApi.strategyMonitorStatus(),
      strategyApi.runAll({ as_of: null, limit: 30, refresh: false }),
    ])
    if (statusRes.status === 'fulfilled') {
      const items = (statusRes.value as any)?.data?.items ?? []
      strategyMonitors.value = items
    }
    if (listRes.status === 'fulfilled') {
      const data = (listRes.value as any)?.data ?? {}
      const counts: Record<string, number> = {}
      for (const s of data?.strategies ?? []) counts[s.id] = s.count
      strategyHitCount.value = counts
    }
  } catch (e) {
    console.warn('加载策略监控概览失败', e)
  }
}

const toggleStrategyMonitor = async (sm: StrategyMonitorStatus, on: boolean) => {
  strategyToggling.value = sm.strategy_id
  try {
    await monitorApi.toggleStrategyMonitor(sm.strategy_id, on, sm.name)
    const item = strategyMonitors.value.find((x) => x.strategy_id === sm.strategy_id)
    if (item) item.enabled = on
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || '未知错误'))
  } finally {
    strategyToggling.value = null
  }
}

const loadTbsOrders = async () => {
  loadingOrders.value = true
  try {
    const res = await monitorApi.listTbsOrders({
      status: tbsStatusFilter.value === 'all' ? undefined : tbsStatusFilter.value,
    })
    tbsOrders.value = (res as any)?.data?.orders ?? []
  } catch (e: any) {
    console.warn('加载三买三卖指令失败', e)
    tbsOrders.value = []
  } finally {
    loadingOrders.value = false
  }
}

const pendingOrders = computed(() => tbsOrders.value.filter((o) => o.status === 'pending'))
const buyPending = computed(() => pendingOrders.value.filter((o) => o.direction === 'buy').length)
const sellPending = computed(() => pendingOrders.value.filter((o) => o.direction === 'sell').length)

// ── 流程总览：自选股 / 持仓数量 ─────────────────────────
const watchlistCount = ref(0)
const positionCount = ref(0)

const loadFlowCounts = async () => {
  try {
    const fav = await favoritesApi.list()
    watchlistCount.value = (fav as any)?.length ?? 0
  } catch { watchlistCount.value = 0 }
  try {
    const pos = await paperApi.getPositions()
    const items = (pos as any)?.data?.items ?? []
    positionCount.value = items.length
  } catch { positionCount.value = 0 }
}

const goOrders = () => {
  activeTab.value = 'orders'
  tbsStatusFilter.value = 'pending'
}

const statusLabel = (status: string): string =>
  ({ pending: '待确认', executed: '已执行', cancelled: '已取消', dismissed: '已忽略' })[status] || status

const pctLabel = (pct?: number): string => {
  if (pct == null) return '—'
  const v = Math.round((pct || 0) * 100)
  return pct >= 1 ? '清仓' : `${v}%`
}

const executeOrder = async (o: TbsOrder) => {
  if (o.direction === 'buy') {
    // 买入：弹窗让用户调整数量后确认（默认一手）
    execOrder.value = o
    execQty.value = 100
    execConfirmVisible.value = true
    return
  }
  await doExecute(o)
}

const doExecute = async (o: TbsOrder) => {
  executingId.value = o.id
  try {
    await monitorApi.executeTbsOrder(o.id, o.direction === 'buy' ? execQty.value : undefined)
    ElMessage.success(`已执行 ${o.symbol} 指令`)
    execConfirmVisible.value = false
    await loadTbsOrders(); await loadFlowCounts()
  } catch (e: any) {
    ElMessage.error('执行失败：' + (e?.message || '未知错误'))
  } finally {
    executingId.value = null
  }
}

const cancelOrder = async (o: TbsOrder) => {
  try {
    await monitorApi.cancelTbsOrder(o.id)
    ElMessage.success('指令已取消')
    await loadTbsOrders()
  } catch (e: any) {
    ElMessage.error('取消失败：' + (e?.message || '未知错误'))
  }
}

const dismissOrder = async (o: TbsOrder) => {
  try {
    await monitorApi.dismissTbsOrder(o.id)
    await loadTbsOrders()
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || '未知错误'))
  }
}

// ── 汇总指标 ──────────────────────────────────────────
const todayStart = () => {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
}
const todayCount = computed(() => alerts.value.filter(a => a.ts >= todayStart()).length)
const criticalCount = computed(() => alerts.value.filter(a => a.severity === 'critical').length)
const enabledRules = computed(() => rules.value.filter(r => r.enabled).length)
const sourceCounts = computed(() => {
  const counts = { signal: 0, price: 0, market: 0 }
  for (const a of alerts.value) {
    const s = (a.source || a.rule_type) as keyof typeof counts
    if (s in counts) counts[s]++
  }
  return counts
})

// ── 加载数据 ───────────────────────────────────────────
const loadOptions = async () => {
  try {
    const res = await monitorApi.getOptions()
    const data = (res as any)?.data ?? {}
    Object.assign(options, data)
  } catch (e) {
    console.warn('加载监控选项失败', e)
  }
}

const loadAlerts = async () => {
  try {
    const res = await monitorApi.listAlerts({
      days: 7, limit: 500,
      source: sourceFilter.value === 'all' ? undefined : sourceFilter.value,
    })
    const data = (res as any)?.data ?? {}
    alerts.value = data.alerts || []
  } catch (e) {
    console.warn('加载触发记录失败', e)
  }
}

const loadRules = async () => {
  try {
    const res = await monitorApi.listRules()
    const data = (res as any)?.data ?? {}
    rules.value = data.rules || []
  } catch (e) {
    console.warn('加载监控规则失败', e)
  }
}

const loadAll = async () => {
  loading.value = true
  await Promise.all([loadOptions(), loadAlerts(), loadRules(), loadTbsOrders(), loadFlowCounts(), loadStrategyMonitors()])
  loading.value = false
}

// ── 手动评估 ──────────────────────────────────────────
const manualCheck = async () => {
  checking.value = true
  try {
    const res = await monitorApi.manualCheck()
    const data = (res as any)?.data ?? {}
    // 重新拉取指令与触发记录
    await Promise.all([loadTbsOrders(), loadAlerts(), loadStrategyMonitors()])
    const pending = pendingOrders.value
    if (pending.length) {
      ElMessage.success(`评估完成，生成 ${pending.length} 条待确认指令`)
      pendingVisible.value = true
    } else {
      ElMessage.success(`评估完成，触发 ${data.triggered ?? 0} 条，暂无待处理指令`)
    }
  } catch (e: any) {
    ElMessage.error('评估失败：' + (e?.message || '未知错误'))
  } finally {
    checking.value = false
  }
}

// ── 触发记录操作 ──────────────────────────────────────
const confirmClear = async () => {
  try {
    await ElMessageBox.confirm(`将删除全部 ${alerts.value.length} 条触发记录，此操作不可撤销。`, '清空触发记录', {
      type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await monitorApi.clearAlerts()
    ElMessage.success('触发记录已清空')
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('清空失败：' + (e?.message || '未知错误'))
  }
}

const deleteAlert = async (id: string) => {
  try {
    await monitorApi.deleteAlert(id)
    ElMessage.success('记录已删除')
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || '未知错误'))
  }
}

// ── 规则操作 ──────────────────────────────────────────
const toggleEnabled = async (rule: MonitorRule) => {
  try {
    await monitorApi.saveRule({ ...rule, enabled: !rule.enabled })
    await loadRules()
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || '未知错误'))
  }
}

const deleteRule = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定删除该监控规则？', '删除规则', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await monitorApi.deleteRule(id)
    ElMessage.success('规则已删除')
    await loadRules()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || '未知错误'))
  }
}

// ── 对话框：类型选择 / 策略阶段 ─────────────────────────
const typeCards = computed(() => [
  { key: 'signal', label: '信号监控', desc: '涨停 / 跌停 / 涨幅跌幅等信号', icon: Aim },
  { key: 'price', label: '价格/涨跌监控', desc: '最新价 / 涨跌幅 / 成交额等阈值', icon: TrendCharts },
  { key: 'market', label: '市场异动监控', desc: '全市场行情异动', icon: FullScreen },
  { key: 'aux', label: '辅助信号预警', desc: '量价背离 / 顶背离等预警', icon: Warning },
])

const openCreate = () => {
  editingRule.value = null
  Object.assign(draft, {
    id: genRuleId(), name: '', enabled: true, type: 'signal', scope: 'watchlist',
    symbols: [], conditions: [], logic: 'and', cooldown_seconds: 3600,
    severity: 'warn', message: '',
  })
  editorVisible.value = true
}

const openEdit = (rule: MonitorRule) => {
  editingRule.value = rule
  Object.assign(draft, {
    id: rule.id, name: rule.name, enabled: rule.enabled, type: rule.type, scope: rule.scope,
    symbols: [...(rule.symbols || [])],
    user_id: rule.user_id,
    conditions: (rule.conditions || []).map((c) => ({ ...c })),
    logic: rule.logic || 'and', cooldown_seconds: rule.cooldown_seconds ?? 3600,
    severity: rule.severity || 'info', message: rule.message || '',
  })
  editorVisible.value = true
}

// ── 条件编辑 ──────────────────────────────────────────
const signalFieldOptions = computed(() =>
  draft.type === 'aux'
    ? (options.aux_fields && options.aux_fields.length ? options.aux_fields : options.signal_fields)
    : options.signal_fields
)
const addSignalCond = () => {
  const field = signalFieldOptions.value[0]?.key || 'signal_limit_up'
  draft.conditions.push({ field, op: 'truth' })
}
const addThresholdCond = () => {
  const field = options.threshold_fields[0]?.key || 'pct_chg'
  draft.conditions.push({ field, op: '>', value: 0 })
}
const removeCond = (idx: number) => { draft.conditions.splice(idx, 1) }
const condPrefix = (idx: number) => (idx === 0 ? '当' : draft.logic === 'and' ? '且' : '或')
const condOps = (cond: MonitorCondition) => {
  if (cond.op === 'truth') return ['truth']
  return options.operators.length ? options.operators : ['>', '>=', '<', '<=', '==', '!=']
}
const opLabel = (op: string) => (op === 'truth' ? '为真' : op)

const saveRule = async () => {
  if (draft.scope === 'symbols' && draft.symbols.length === 0) {
    ElMessage.warning('请至少选择一只标的')
    return
  }
  if (draft.conditions.length === 0) {
    ElMessage.warning('请至少添加一个触发条件')
    return
  }
  for (const c of draft.conditions) {
    if (c.op !== 'truth' && (c.value === null || c.value === undefined)) {
      ElMessage.warning('阈值条件需要填写数值')
      return
    }
  }
  saving.value = true
  try {
    const payload: any = {
      id: draft.id, name: draft.name, enabled: draft.enabled, type: draft.type,
      scope: draft.scope, symbols: draft.symbols, conditions: draft.conditions,
      logic: draft.logic, cooldown_seconds: draft.cooldown_seconds,
      severity: draft.severity, message: draft.message,
    }
    if (!payload.name.trim()) {
      const base = { signal: '信号监控', price: '价格监控', market: '市场异动监控', aux: '辅助信号预警' }[draft.type] || '监控规则'
      if (draft.scope === 'watchlist') {
        payload.name = `${base} · 自选股`
      } else {
        payload.name = draft.scope === 'symbols' && draft.symbols.length > 0
          ? `${base} · ${draft.symbols[0]}${draft.symbols.length > 1 ? ` 等${draft.symbols.length}只` : ''}`
          : base
      }
    }
    await monitorApi.saveRule(payload)
    ElMessage.success('规则保存成功')
    editorVisible.value = false
    await loadRules()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

// ── 展示辅助 ──────────────────────────────────────────
const typeLabel = (t: string) => {
  const map: Record<string, string> = { signal: '信号', price: '价格/涨跌', market: '市场异动', aux: '辅助信号预警' }
  return map[t] || t
}
const typeTag = (t: string): 'success' | 'info' | 'warning' | 'primary' => {
  const map: Record<string, any> = { signal: 'success', price: 'warning', market: 'primary', aux: 'info' }
  return map[t] || 'info'
}
const sourceLabel = (s: string) => {
  const map: Record<string, string> = { signal: '信号', price: '价格/涨跌', market: '市场异动', aux: '辅助信号预警' }
  return map[s] || s
}
const severityTag = (s: string): 'info' | 'warning' | 'danger' => {
  const map: Record<string, any> = { info: 'info', warn: 'warning', critical: 'danger' }
  return map[s] || 'info'
}
const scopeLabel = (s: string) => (s === 'all' ? '全市场' : s === 'watchlist' ? '自选股' : s === 'positions' ? '纸面持仓' : '指定标的')
const fieldLabel = (f: string) => {
  const all = [...options.threshold_fields, ...options.signal_fields, ...(options.aux_fields || [])]
  const found = all.find((item) => item.key === f)
  return found ? found.label : f
}

// ── 全市场作用域字段可用性 ─────────────────────────────
const ALL_SCOPE_UNAVAILABLE_FIELDS = ['change_amt', 'turnover_pct', 'mcap_yi', 'pe_ttm', 'pb']
const isThresholdFieldAvailable = (key: string) =>
  draft.scope !== 'all' || !ALL_SCOPE_UNAVAILABLE_FIELDS.includes(key)
const thresholdFieldTip = (f: { key: string; label: string }) =>
  `全市场作用域下无法获取「${f.label}」，请改用「指定标的」或使用 最新价 / 涨跌幅 / 成交额`
const formatTs = (ts: number) => {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── 轮询 ──────────────────────────────────────────────
const startPolling = () => {
  stopPolling()
  pollTimer = window.setInterval(() => {
    loadAlerts(); loadRules(); loadTbsOrders(); loadFlowCounts(); loadStrategyMonitors()
  }, 30000)
}
const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onMounted(() => { loadAll(); startPolling() })
onBeforeUnmount(() => { stopPolling() })
</script>

<style lang="scss" scoped>
.monitor-center {
  .monitor-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
    .monitor-tip { margin-left: auto; font-size: 12px; color: var(--el-text-color-secondary); }
  }

  // ── 策略流程总览 ─────────────────────────────────
  .flow-panel {
    padding: 16px 20px;
    margin-bottom: 16px;
    border-radius: 12px;
    background: linear-gradient(135deg, #f6f9ff 0%, #eef4ff 100%);
    border: 1px solid #dfe8fb;

    .flow-title {
      display: flex; align-items: center; gap: 6px;
      font-weight: 600; font-size: 14px; color: #2b6cb0;
      .flow-sub { font-weight: 400; font-size: 12px; color: var(--el-text-color-secondary); }
    }

    .flow-track {
      display: flex; align-items: stretch; justify-content: space-between;
      margin-top: 14px; gap: 4px;
    }

    .flow-node {
      flex: 1; min-width: 0;
      display: flex; align-items: center; gap: 10px;
      padding: 12px 14px;
      background: #fff; border: 1px solid #e3ebfb; border-radius: 10px;
      transition: box-shadow .2s, transform .2s;

      &.clickable { cursor: pointer; &:hover { box-shadow: 0 4px 14px rgba(43,108,176,.15); transform: translateY(-2px); } }
      &.hot { border-color: #f56c6c; box-shadow: 0 0 0 2px rgba(245,108,108,.15); }
      &.dim { opacity: .75; }

      .flow-ico {
        width: 40px; height: 40px; border-radius: 10px; flex-shrink: 0;
        display: flex; align-items: center; justify-content: center; font-size: 20px; color: #fff;
        &.watch { background: #2b6cb0; }
        &.buy { background: #f56c6c; }
        &.pos { background: #9261d6; }
        &.sell { background: #67c23a; }
        &.out { background: #909399; }
      }

      .flow-info { min-width: 0; }
      .flow-name { font-size: 12px; color: var(--el-text-color-secondary); }
      .flow-num { font-size: 22px; font-weight: 700; font-family: monospace; color: #1f2d3d; line-height: 1.1; }
      .flow-desc { font-size: 11px; color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    }

    .flow-arrow {
      display: flex; align-items: center; justify-content: center; color: #2b6cb0; opacity: .5; flex-shrink: 0;
      span { font-size: 12px; }
    }
  }

  // ── 常用策略监控概览 ─────────────────────────────
  .strategy-overview {
    padding: 16px 20px;
    margin-bottom: 16px;
    border-radius: 12px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-lighter);

    .overview-head {
      display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;
      .overview-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 14px; color: var(--el-text-color-primary);
        .overview-sub { font-weight: 400; font-size: 12px; color: var(--el-text-color-secondary); }
      }
    }

    .strategy-chip-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px;
    }
    .strategy-chip {
      display: flex; align-items: center; gap: 10px; padding: 12px;
      border: 1px solid var(--el-border-color-lighter); border-radius: 10px;
      transition: box-shadow .2s, border-color .2s;
      &.on { border-color: #2b6cb0; box-shadow: 0 0 0 2px rgba(43,108,176,.12); }
      .chip-ico { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 17px; background: #2b6cb0; flex-shrink: 0;
        &.on { background: #2b6cb0; } }
      .chip-main { flex: 1; min-width: 0;
        .chip-name { font-size: 13px; font-weight: 600; }
        .chip-desc { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; }
      }
    }
  }

  // ── 待确认指令弹窗 ──────────────────────────────
  .pending-empty { padding: 24px; text-align: center; color: var(--el-text-color-secondary); font-size: 13px; }
  .pending-list { display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow-y: auto;
    .pending-item { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-blank);
      .p-dir { width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 600; flex-shrink: 0; font-size: 13px;
        &.buy { background: var(--el-color-danger); } &.sell { background: var(--el-color-success); } }
      .p-main { flex: 1; min-width: 0;
        .p-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
          .p-symbol { font-family: monospace; font-weight: 600; font-size: 13px; }
          .p-name { font-size: 12px; color: var(--el-text-color-secondary); } }
        .p-reason { margin-top: 4px; font-size: 12px; color: var(--el-text-color-regular); }
      }
      .p-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
    }
  }

  // ── 主内容 Tab ──────────────────────────────────
  .monitor-tabs {
    :deep(.el-tabs__header) { margin-bottom: 16px; }
    .tab-label { display: inline-flex; align-items: center; gap: 6px; }
    .tab-badge { margin-left: 4px; }
    .tab-count { margin-left: 4px; }
  }

  .monitor-card { margin-bottom: 16px;
    .card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;
      .card-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
      .card-actions { display: flex; align-items: center; gap: 8px; }
    }
  }

  .empty-hint { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 8px; }

  // ── 规则列表 ────────────────────────────────────
  .rules-list { display: flex; flex-direction: column; gap: 8px;
    .rule-item { display: flex; gap: 10px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-blank); transition: box-shadow .2s;
      &:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
      &.disabled { opacity: .6; }
      .rule-status-bar { width: 3px; border-radius: 2px; flex-shrink: 0; &.on { background: var(--el-color-primary); } &.off { background: var(--el-border-color); } }
      .rule-main { flex: 1; min-width: 0;
        .rule-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
          .rule-name { font-size: 13px; font-weight: 600; }
          .rule-desc { font-size: 11px; color: var(--el-text-color-secondary); } }
        .rule-meta { margin-top: 4px; display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--el-text-color-secondary);
          .rule-symbols { font-family: monospace; } }
        .rule-conditions { margin-top: 4px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-size: 12px;
          .cond-logic { color: var(--el-text-color-secondary); } .cond-item { color: var(--el-color-primary); font-family: monospace; } .cond-more { color: var(--el-text-color-secondary); } }
      }
      .rule-actions { display: flex; align-items: center; flex-shrink: 0; .act-on { color: var(--el-color-primary); } }
    }
  }

  // ── 触发记录 ────────────────────────────────────
  .monitor-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px;
    .stat-item { flex: 1; min-width: 120px; padding: 12px; border-radius: 8px; background: var(--el-fill-color-light); text-align: center;
      .stat-num { font-size: 24px; font-weight: 700; color: var(--el-color-primary); font-family: monospace;
        &.active { color: var(--el-color-warning); } &.danger { color: var(--el-color-danger); }
        .stat-sub { font-size: 13px; font-weight: 400; color: var(--el-text-color-secondary); } }
      .stat-label { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); } }
  }

  .alerts-list { max-height: 560px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px;
    .alert-item { display: flex; gap: 10px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-blank); transition: box-shadow .2s;
      &:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
      .alert-severity-bar { width: 3px; border-radius: 2px; flex-shrink: 0; &.info { background: var(--el-color-primary); } &.warn { background: var(--el-color-warning); } &.critical { background: var(--el-color-danger); } }
      .alert-main { flex: 1; min-width: 0;
        .alert-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
          .alert-symbol { font-family: monospace; font-weight: 600; font-size: 13px; }
          .alert-name { font-size: 12px; color: var(--el-text-color-secondary); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .alert-price { font-family: monospace; font-size: 13px; font-weight: 600; &.up { color: var(--el-color-danger); } &.down { color: var(--el-color-success); } }
          .alert-pct { font-family: monospace; font-size: 12px; &.up { color: var(--el-color-danger); } &.down { color: var(--el-color-success); } }
        }
        .alert-message { margin-top: 4px; font-size: 12px; color: var(--el-text-color-regular); }
        .alert-conditions { margin-top: 4px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-size: 12px;
          .cond-label { color: var(--el-text-color-secondary); } .cond-logic { color: var(--el-text-color-secondary); } .cond-item { color: var(--el-color-primary); font-family: monospace; } }
      }
      .alert-side { display: flex; flex-direction: column; align-items: flex-end; justify-content: space-between; flex-shrink: 0;
        .alert-time { font-size: 11px; color: var(--el-text-color-placeholder); font-family: monospace; } }
    }
  }

  // ── 待确认指令 ──────────────────────────────────
  .tbs-list { display: flex; flex-direction: column; gap: 8px;
    .tbs-item { display: flex; gap: 12px; padding: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-blank); transition: box-shadow .2s;
      &:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
      &.done { opacity: .6; }
      .tbs-dir { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 600; flex-shrink: 0;
        &.buy { background: var(--el-color-danger); } &.sell { background: var(--el-color-success); } }
      .tbs-main { flex: 1; min-width: 0;
        .tbs-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
          .tbs-symbol { font-family: monospace; font-weight: 600; font-size: 13px; }
          .tbs-name { font-size: 12px; color: var(--el-text-color-secondary); } }
        .tbs-meta { margin-top: 4px; display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: var(--el-text-color-secondary); }
        .tbs-reason { margin-top: 4px; font-size: 12px; color: var(--el-text-color-regular); }
        .tbs-result { margin-top: 4px; font-size: 12px; color: var(--el-color-success); }
      }
      .tbs-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
    }
  }

  // ── 对话框 ──────────────────────────────────────
  .rule-form {
    .form-section { margin-bottom: 18px;
      .form-section-title { font-weight: 600; font-size: 13px; margin-bottom: 10px; color: var(--el-text-color-primary); }
    }

    .type-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
    .type-card { position: relative; padding: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; cursor: pointer; text-align: center; transition: all .2s; background: var(--el-fill-color-blank);
      &:hover { border-color: #2b6cb0; }
      &.active { border-color: #2b6cb0; box-shadow: 0 0 0 2px rgba(43,108,176,.15); background: #f0f6ff; }
      .type-ico { width: 34px; height: 34px; margin: 0 auto 6px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 17px;
        &.signal { background: #67c23a; } &.price { background: #e6a23c; } &.market { background: #9261d6; } &.aux { background: #909399; } }
      .type-name { font-size: 13px; font-weight: 600; }
      .type-desc { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; line-height: 1.4; }
    }

    .scope-hint { margin-left: 8px; font-size: 12px; color: var(--el-color-primary); display: inline-flex; align-items: center; gap: 4px; }

    .cond-editor { width: 100%;
      .cond-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
      .cond-empty { padding: 16px; text-align: center; border: 1px dashed var(--el-border-color); border-radius: 6px; color: var(--el-text-color-secondary); font-size: 12px; }
      .cond-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
        .cond-logic-prefix { width: 20px; text-align: right; color: var(--el-text-color-secondary); font-size: 12px; flex-shrink: 0; }
      }
    }
  }

  // ── 移动端适配 ──────────────────────────────────
  @media (max-width: 768px) {
    .monitor-toolbar {
      flex-wrap: wrap;
      gap: 8px;
      .monitor-tip {
        margin-left: 0;
        width: 100%;
        order: 3;
        font-size: 11px;
      }
    }

    .flow-panel {
      padding: 12px;

      .flow-title {
        flex-wrap: wrap;
        .flow-sub {
          display: none;
        }
      }

      .flow-track {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        flex-wrap: nowrap;
        min-width: max-content;
        padding-bottom: 4px;
      }

      .flow-node {
        flex: 0 0 auto;
        width: 130px;
        padding: 10px;
        gap: 8px;
        flex-direction: column;
        text-align: center;

        .flow-ico {
          width: 32px;
          height: 32px;
          font-size: 16px;
        }

        .flow-info {
          width: 100%;
        }

        .flow-name {
          font-size: 11px;
        }

        .flow-num {
          font-size: 18px;
        }

        .flow-desc {
          font-size: 10px;
        }
      }

      .flow-arrow {
        flex: 0 0 auto;
      }
    }

    .strategy-overview {
      padding: 12px;

      .overview-head {
        flex-direction: column;
        align-items: stretch;
        gap: 8px;
      }

      .overview-title {
        font-size: 13px;
        .overview-sub {
          font-size: 11px;
        }
      }

      .strategy-chip-grid {
        grid-template-columns: 1fr;
      }
    }

    .monitor-tabs {
      :deep(.el-tabs__header) {
        margin-bottom: 12px;
        .el-tabs__nav-wrap {
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
        }
      }
    }

    .monitor-card {
      margin-bottom: 12px;

      .card-header {
        flex-direction: column;
        align-items: stretch;
        gap: 10px;

        .card-actions {
          width: 100%;
          overflow-x: auto;
        }
      }
    }

    .tbs-list {
      .tbs-item {
        flex-direction: column;
        gap: 10px;

        .tbs-actions {
          width: 100%;
          justify-content: flex-end;
        }

        .tbs-main {
          width: 100%;
        }

        .tbs-top {
          flex-wrap: wrap;
        }

        .tbs-meta {
          flex-wrap: wrap;
          gap: 6px;
        }
      }
    }

    .rules-list {
      .rule-item {
        flex-direction: column;
        gap: 8px;

        .rule-actions {
          width: 100%;
          justify-content: flex-end;
        }
      }
    }

    .alerts-list {
      .alert-item {
        flex-direction: column;
        gap: 8px;

        .alert-side {
          flex-direction: row;
          align-items: center;
          width: 100%;
          justify-content: space-between;
        }
      }
    }

    .monitor-stats {
      .stat-item {
        min-width: calc(50% - 6px);
      }
    }
  }
}
</style>