<template>
  <div class="vibe-market app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }}<em v-if="weekday" class="title-weekday">（{{ weekday }}）</em> · 大盘研判</h2>
          <p class="page-hero-sub">今日结论 → 当前位置 → 盘中事实 → 事件与类比，一条决策链</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="market-state" :class="marketState.cls">{{ marketState.label }}</span>
        <span class="page-hero-tag">数据 {{ dataAsOf || '—' }} · 更新 {{ updatedAt || '—' }}</span>
        <el-button type="primary" plain :icon="Refresh" :loading="loading || synLoading" @click="refreshAll">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 01 今日结论：方向 / 信心度 / 一句话结论 / 主攻·回避·仓位 -->
    <section id="verdict" class="mr-sec">
      <div class="mr-sec-head">
        <span class="mr-sec-no">01</span>
        <span class="mr-sec-title">今日结论</span>
        <span class="mr-sec-hint">先看结论，下面各层都是它的依据</span>
        <span v-if="position?.divergence?.length" class="mr-div-badge" @click="scrollTo('position')">
          背离预警 {{ position.divergence.length }}
        </span>
        <span class="mr-sec-actions">
          <span v-if="syn?.as_of" class="data-time">研判 {{ shortTime(syn.as_of) }}</span>
          <el-button link type="primary" :loading="synLoading" @click="loadSynthesis(true)">AI 重新研判</el-button>
        </span>
      </div>

      <div v-if="synLoading && !syn" class="syn-loading">
        <el-skeleton :rows="5" animated />
        <div class="syn-loading-tip">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在加载综合研判（命中缓存秒开，冷启动需 10~60 秒）…
        </div>
      </div>

      <section v-else-if="verdict" class="syn-hero" :class="'syn-hero--' + verdict.dirClass">
        <!-- 顶部：方向 + 信心度 + 标签 -->
        <div class="syn-hero-top">
          <div class="syn-direc-wrap">
            <span class="syn-direc-zh">{{ verdict.directionZh }}方向</span>
            <span class="syn-direc-main">{{ verdict.direction }}</span>
          </div>
          <el-popover
            v-if="verdict.confidence != null"
            placement="bottom"
            :width="272"
            trigger="hover"
            :disabled="!events.length"
          >
            <template #reference>
              <div class="syn-conf-wrap">
                <div class="syn-conf-ring" :style="confRingStyle">
                  <span class="syn-conf-num">{{ verdict.confidence }}</span>
                  <span class="syn-conf-unit">%</span>
                </div>
                <span class="syn-conf-label">信心度<em v-if="events.length" class="conf-badge">含事件</em></span>
              </div>
            </template>
            <div class="conf-pop">
              <div class="conf-pop-title">信心度已计入以下事件（只修正，不覆盖趋势判断）</div>
              <div v-for="e in events" :key="e.id" class="conf-pop-row">
                <span>{{ e.time }} {{ shortTitle(e.title) }}</span>
                <em :class="`dir-${e.direction}`">{{ dirLabel(e.direction) }}</em>
              </div>
            </div>
          </el-popover>
          <div class="syn-tags">
            <el-tag v-if="syn?.llm_available" size="small" type="danger" effect="dark">AI 研判</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">规则兜底</el-tag>
          </div>
        </div>

        <div class="syn-hero-concl">
          <div class="syn-concl-text">{{ verdict.conclusion }}</div>
        </div>

        <div class="syn-decision" v-if="hasOperationPoints">
          <div class="syn-dec-card syn-dec-card--main" v-if="verdict.operation_points.main_direction">
            <div class="syn-dec-label">主攻</div>
            <div class="syn-dec-text">{{ verdict.operation_points.main_direction }}</div>
          </div>
          <div class="syn-dec-card syn-dec-card--avoid" v-if="verdict.operation_points.avoid_direction">
            <div class="syn-dec-label">回避</div>
            <div class="syn-dec-text">{{ verdict.operation_points.avoid_direction }}</div>
          </div>
          <div class="syn-dec-card syn-dec-card--pos" v-if="verdict.operation_points.position_discipline">
            <div class="syn-dec-label">仓位</div>
            <div class="syn-dec-text">{{ verdict.operation_points.position_discipline }}</div>
          </div>
        </div>
      </section>

      <el-empty
        v-else
        :image-size="72"
        description="本次未获取到研判结论（AI 与规则兜底均不可用），可点「AI 重新研判」重试"
      />
    </section>

    <!-- 02 当前位置：把今天放进近 10 年历史，回答「贵不贵、热不热、接近顶还是底」 -->
    <section id="position" class="mr-sec">
      <div class="mr-sec-head">
        <span class="mr-sec-no">02</span>
        <span class="mr-sec-title">当前位置</span>
        <span class="mr-sec-hint">估值 / 位置 / 情绪 / 参与度 / 底部特征的历史分位（近 10 年），用来判断「接近顶部」还是「接近底部」</span>
        <span class="mr-sec-actions">
          <span v-if="position?.as_of" class="data-time">数据 {{ position.as_of }}</span>
        </span>
      </div>

      <div v-if="positionLoading && !position" class="syn-loading">
        <el-skeleton :rows="4" animated />
        <div class="syn-loading-tip">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在计算历史分位（首次构建需 1~2 分钟）…
        </div>
      </div>

      <div v-else-if="!position || !position.ready" class="pos-pending">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ position?.note || '历史分位基线构建中，完成后自动显示' }}</span>
        <el-button link type="primary" @click="loadPosition(true)">立即重试</el-button>
      </div>

      <template v-else>
        <!-- 位置标尺：0–100 分位 + 五档分区 + 指针；回答「现在离顶 / 离底有多远」 -->
        <div class="pos-hero" :class="'zone-' + position.composite.zone">
          <div class="pos-hero-head">
            <div class="pos-hero-left">
              <span class="pos-zone-badge">{{ position.composite.label }}</span>
              <div class="pos-verdict">
                <div class="pos-verdict-title">{{ posVerdict.title }}</div>
                <div class="pos-verdict-sub">{{ posVerdict.sub }}</div>
              </div>
            </div>
            <div class="pos-hero-score">
              <div class="pos-score-num">{{ compositePct ?? '—' }}<em>%</em></div>
              <div class="pos-score-cap">合成分位</div>
            </div>
          </div>

          <div class="pos-gauge">
            <div class="pos-gauge-bar">
              <i
                v-for="z in GAUGE_BANDS"
                :key="z.key"
                class="pos-gauge-band"
                :class="z.key"
                :style="{ width: z.width + '%' }"
              >{{ z.name }}</i>
              <i v-if="compositePct != null" class="pos-gauge-needle" :style="{ left: compositePct + '%' }" />
              <em v-if="compositePct != null" class="pos-gauge-bubble" :style="{ left: compositePct + '%' }">{{ compositePct }}%</em>
            </div>
            <div class="pos-gauge-scale">
              <span v-for="t in GAUGE_TICKS" :key="t" :style="{ left: t + '%' }">{{ t }}</span>
            </div>
            <div class="pos-gauge-dots">
              <el-tooltip
                v-for="d in heatDots"
                :key="d.key"
                :content="`${d.label}：热度分位 ${d.pct}%`"
                placement="top"
              >
                <span
                  class="pos-gauge-dot"
                  :class="[d.tone, { 'is-low': d.row }]"
                  :style="{ left: d.pct + '%' }"
                />
              </el-tooltip>
            </div>
          </div>

          <div class="pos-distance">
            <span
              v-for="c in posDistance"
              :key="c.key"
              class="pos-distance-chip"
              :class="c.tone"
            >{{ c.text }}</span>
            <span class="pos-distance-chip is-meta">
              {{ position.window_years }} 年 · {{ position.samples }} 个交易日样本 · 截至 {{ position.as_of }}
            </span>
          </div>

          <p class="pos-advice">{{ position.composite.advice }}</p>
        </div>

        <!-- 逃顶 / 判断底部：触发阈值 + 历史同档位的真实表现（不是口号） -->
        <div v-if="posGuides.length" class="pos-guide">
          <div
            v-for="g in posGuides"
            :key="g.key"
            class="pos-guide-card"
            :class="[`is-${g.key}`, { 'is-active': g.active }]"
          >
            <div class="pos-guide-head">
              <span class="pos-guide-title">{{ g.title }}</span>
              <em class="pos-guide-flag" :class="{ 'is-on': g.active }">
                {{ g.active ? '当前已进入该区' : `触发 ${g.key === 'top' ? '≥' : '≤'}${g.threshold ?? (g.key === 'top' ? 80 : 20)}` }}
              </em>
            </div>
            <div class="pos-guide-track">
              <i class="pos-guide-zone" :class="`is-${g.key}`" />
              <i v-if="compositePct != null" class="pos-guide-cursor" :style="{ left: compositePct + '%' }">
                <b>{{ compositePct }}</b>
              </i>
            </div>
            <div class="pos-guide-rule">{{ g.rule }}</div>
            <div class="pos-guide-stats">{{ g.stats }}</div>
            <div class="pos-guide-advice">{{ g.advice }}</div>
          </div>
        </div>

        <!-- 合成分位是什么：7 项热度分位的平均 + 当前内部结构 -->
        <div class="pos-explain">
          <div class="pos-explain-text">
            <el-icon><InfoFilled /></el-icon>
            <span>
              合成分位 = 把 {{ componentHeat.length }} 个长历史指标各自折算成 0–100 的「热度分位」再取平均：
              0% ≈ 近 {{ position.window_years }} 年最冷，100% ≈ 最热；≥80 为逃顶信号区，≤20 为判底观察区。
            </span>
          </div>
          <div class="pos-comp-chips">
            <span
              v-for="c in componentHeat"
              :key="c.key"
              class="pos-comp-chip"
              :class="c.tone"
            >
              <i /><em>{{ c.label }}</em><b>{{ c.pct }}%</b>
            </span>
          </div>
          <div v-if="heatSpread" class="pos-spread">
            <el-icon><WarnTriangleFilled /></el-icon>
            <span>{{ heatSpread.text }}</span>
          </div>
        </div>

        <!-- 近 10 年合成分位走势：红线 80 逃顶、绿线 20 判底 -->
        <div v-if="compositeChartOption" class="pos-chart">
          <div class="pos-block-head">
            近 {{ position.window_years }} 年合成分位走势
            <span class="dist-note">虚线：上 80 逃顶 / 下 20 判底 · 每个点为一个交易日（等距抽稀）</span>
          </div>
          <VChart :option="compositeChartOption" autoresize class="chart-200" />
        </div>

        <!-- 单项指标：分组横条（分位越靠右越热，竖线为 50% 中位） -->
        <div class="pos-metrics">
          <div v-for="grp in positionGroups" :key="grp.group" class="pos-group">
            <div class="pos-group-head">
              {{ grp.group }}<span class="pos-group-hint">{{ grp.hint }}</span>
            </div>
            <div class="pos-bullets">
              <div v-for="m in grp.items" :key="m.key" class="pos-bullet">
                <el-tooltip :content="m.desc" placement="top" :show-after="200">
                  <span class="pos-bullet-label">{{ m.label }}<el-icon><QuestionFilled /></el-icon></span>
                </el-tooltip>
                <div class="pos-bullet-track">
                  <i
                    v-if="m.percentile != null"
                    class="pos-bullet-fill"
                    :class="posTone(heatOfMetric(m))"
                    :style="{ width: m.percentile + '%' }"
                  />
                  <i class="pos-bullet-med" title="中位 = 50% 分位" />
                </div>
                <span class="pos-bullet-value">{{ m.value == null ? '—' : m.value }}<em>{{ m.unit }}</em></span>
                <span class="pos-bullet-pct" :class="posTone(heatOfMetric(m))">
                  {{ m.percentile == null ? '—' : m.percentile + '%' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="position.divergence.length" class="pos-div-row">
          <span
            v-for="d in position.divergence"
            :key="d.title + d.detail"
            class="pos-div-chip"
            :class="'is-' + d.level"
          >
            <b>{{ d.title }}</b><span>{{ d.detail }}</span>
          </span>
        </div>

        <!-- 历史分位 → 未来 20 日收益：以 0 为中轴的发散条形 -->
        <div v-if="position.forward" class="pos-fwd">
          <div class="pos-block-head">
            历史分位 → 未来 {{ position.forward.day }} 日收益
            <span class="dist-note">
              等权全市场组合 · n={{ position.forward.samples }} · 近 {{ position.forward.window_years }} 年
            </span>
          </div>
          <div class="pos-fwd-rows">
            <div
              v-for="b in position.forward.bins"
              :key="b.key"
              class="pos-fwd-row"
              :class="{ 'is-current': b.key === position.forward.current_bin }"
            >
              <span class="pos-fwd-label">
                {{ b.label }}
                <em v-if="b.key === position.forward.current_bin">当前</em>
              </span>
              <div class="pos-fwd-track">
                <i class="pos-fwd-zero" />
                <i
                  class="pos-fwd-bar"
                  :class="(b.median_return ?? 0) >= 0 ? 'up' : 'down'"
                  :style="fwdBarStyle(b.median_return)"
                />
              </div>
              <span class="pos-fwd-val mono" :class="clsByVal(b.median_return)">{{ signedPct(b.median_return) }}</span>
              <span class="pos-fwd-meta mono">
                胜率 {{ b.win_rate == null ? '—' : b.win_rate + '%' }} · n={{ b.n }}
              </span>
            </div>
          </div>
          <p class="cap">分位越高代表当时市场越热；收益为未来 {{ position.forward.day }} 个交易日的等权平均涨跌幅，仅作历史统计，不代表未来。</p>
        </div>

        <p class="cap">{{ position.note }}</p>
      </template>
    </section>

    <!-- 03 盘中事实 -->
    <section id="facts" class="mr-sec">
      <div class="mr-sec-head">
        <span class="mr-sec-no">03</span>
        <span class="mr-sec-title">盘中事实</span>
        <span class="mr-sec-hint">指数 / 涨跌分布 / 宽度 / 风格 / 集中度</span>
        <span class="mr-sec-actions">
          <span v-if="metrics?.updated" class="data-time">指标 {{ shortTime(metrics.updated) }}</span>
        </span>
      </div>

    <!-- 开盘情景：盘前唯一的前瞻信息（隔夜外盘 → 开盘缺口）+ 昨日情绪结构，08:30 后自动展开 -->
    <section v-if="preOpen && preOpen.bands.length && isPreOpen" class="preopen-block">
      <div class="preopen-head">
        <span class="preopen-kicker">开盘情景</span>
        <span class="preopen-verdict" :class="`tone-${preOpen.gap.tone}`">
          {{ preOpen.gap.label }}
          <em v-if="preOpen.gap.pct != null">{{ signedPct(preOpen.gap.pct) }}</em>
        </span>
        <span v-if="preOpen.gap.basis_name" class="preopen-basis">
          {{ preOpen.gap.basis_name }} · {{ preOpen.gap.basis_name.includes('A50') ? '夜盘' : '期货' }}
          <span v-if="preOpen.gap.degraded" class="preopen-tag">降级口径</span>
        </span>
        <span class="preopen-actions">
          <span class="data-time">抓取 {{ shortTime(preOpen.as_of) }}</span>
          <span class="preopen-toggle" @click="preOpenOpen = !preOpenOpen">{{ preOpenOpen ? '收起' : '展开' }}</span>
        </span>
      </div>

      <div v-show="preOpenOpen" class="preopen-body">
        <!-- 五档刻度：区间宽度按幅度成比例，指针标出当前实际位置 -->
        <div class="scenario-scale">
          <span
            v-if="scenarioPointerPct != null"
            class="scenario-ptr"
            :class="`tone-${preOpen.gap.tone}`"
            :style="{ left: scenarioPointerPct + '%' }"
          />
          <div class="scenario-track">
            <div
              v-for="b in preOpen.bands"
              :key="b.key"
              class="scenario-seg"
              :class="b.key === preOpen.gap.band ? `active tone-${b.tone}` : ''"
            >
              <span class="seg-label">{{ b.label }}</span>
              <span class="seg-range">{{ bandRange(b) }}</span>
            </div>
          </div>
        </div>

        <div class="preopen-meta">
          <div class="meta-row">
            <span class="meta-label">隔夜外盘</span>
            <div class="meta-items">
              <span
                v-for="it in preOpen.overseas"
                :key="it.key"
                class="meta-item"
                :class="{ 'meta-item--key': it.key === 'a50fut' }"
              >
                <b>{{ it.name }}</b>
                <i :class="colorClass(it.change_pct)">{{ signedPct(it.change_pct) }}</i>
              </span>
            </div>
          </div>
          <div v-if="preOpen.structure" class="meta-row">
            <span class="meta-label">昨日结构</span>
            <div class="meta-items">
              <span class="meta-item">
                <b>涨停</b><i>{{ preOpen.structure.zt }}</i>
                <em :class="deltaClass(preOpen.structure.zt_delta)">{{ deltaText(preOpen.structure.zt_delta) }}</em>
              </span>
              <span class="meta-item">
                <b>最高连板</b><i>{{ preOpen.structure.max_boards }}</i>
                <em :class="deltaClass(preOpen.structure.max_boards_delta)">{{ deltaText(preOpen.structure.max_boards_delta) }}</em>
              </span>
              <span class="meta-item">
                <b>连板</b><i>{{ preOpen.structure.lianban }}</i>
                <em :class="deltaClass(preOpen.structure.lianban_delta)">{{ deltaText(preOpen.structure.lianban_delta) }}</em>
              </span>
              <span class="meta-item">
                <b>封板率</b>
                <i>{{ preOpen.structure.seal_rate == null ? '—' : fmtAbsPct(preOpen.structure.seal_rate * 100, 0) }}</i>
                <em :class="deltaClass(preOpen.structure.seal_delta_pt)">{{ deltaText(preOpen.structure.seal_delta_pt, 'pt') }}</em>
              </span>
              <span class="meta-date">{{ preOpen.structure.date }}</span>
            </div>
          </div>
        </div>

        <div class="preopen-note">{{ preOpen.note }}</div>
      </div>
    </section>
    <section v-else-if="preOpenLoading" class="preopen-block preopen-block--loading">
      <span class="preopen-kicker">开盘情景</span>
      <span class="block-hint"><el-icon class="is-loading"><Loading /></el-icon> 正在计算隔夜外盘与昨日结构</span>
    </section>

    <!-- 大盘指数 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataLine /></el-icon> 大盘指数</span>
        <span v-if="loading" class="block-hint">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中
        </span>
      </div>
      <div class="grid grid-4">
        <el-card
          v-for="item in indices"
          :key="item.name"
          shadow="never"
          class="idx-card"
        >
          <div class="idx-name">{{ item.name }}</div>
          <div class="idx-price">{{ fmtPrice(item.price) }}</div>
          <div class="idx-change" :class="colorClass(item.change_pct)">
            <span class="pct">{{ fmtPct(item.change_pct) }}</span>
            <span class="amt">{{ fmtSigned(item.change_amt) }}</span>
          </div>
        </el-card>
        <el-card v-if="!indices.length && !loading" shadow="never" class="idx-card empty-card">
          <el-empty :image-size="48" description="暂无指数数据" />
        </el-card>
      </div>
    </section>

    <!-- 今日涨跌分布：横截面回答「涨多还是跌多、极端多少」 -->
    <section v-if="dashboard" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Histogram /></el-icon> 今日涨跌分布</span>
        <span class="block-hint">{{ limitNote }}</span>
      </div>

      <!-- 雷达 + 涨跌分布 -->
      <div class="dash-main">
        <el-card shadow="never" class="dash-card">
          <div class="card-title">
            情绪雷达
            <span class="dist-note">虚线 = 50 分中性基准</span>
          </div>
          <div v-if="dashboard.radar.length" class="radar-wrap">
            <svg viewBox="0 0 240 240" class="radar-svg">
              <defs>
                <radialGradient id="emRadarFill" cx="50%" cy="45%" r="70%">
                  <stop offset="0%" :stop-color="scoreHex + '57'" />
                  <stop offset="100%" :stop-color="scoreHex + '1f'" />
                </radialGradient>
              </defs>
              <polygon
                v-for="g in radarGrid"
                :key="g.level"
                :points="g.points"
                :fill="g.idx % 2 === 0 ? 'rgba(128,128,128,0.12)' : 'rgba(128,128,128,0.06)'"
                :stroke="g.level === 1 ? 'rgba(128,128,128,0.5)' : 'rgba(128,128,128,0.25)'"
                :stroke-width="g.level === 1 ? 1.2 : 0.8"
              />
              <line v-for="p in radarPoints" :key="p.key + '-l'" :x1="120" :y1="120" :x2="p.gx" :y2="p.gy" stroke="rgba(128,128,128,0.3)" />
              <!-- 50 分基准环：低于虚线说明该维度不及中性水平 -->
              <polygon :points="radarMidPolygon" fill="none" stroke="rgba(128,128,128,0.45)" stroke-width="1" stroke-dasharray="3 3" />
              <polygon :points="radarPolygon" :fill="'url(#emRadarFill)'" :stroke="scoreHex" stroke-width="2" />
              <circle v-for="p in radarPoints" :key="p.key" :cx="p.x" :cy="p.y" r="2.8" :fill="scoreHex" />
              <text x="120" y="127" text-anchor="middle" class="radar-score">{{ dashboard.emotion.score }}</text>
              <text v-for="p in radarPoints" :key="p.key + '-t'" :x="p.lx" :y="p.ly + 4" text-anchor="middle" class="radar-label" :style="{ cursor: 'help' }">
                {{ p.label }}
                <title>{{ p.label }}：{{ p.value }}分{{ p.desc ? ' — ' + p.desc : '' }}</title>
              </text>
            </svg>
          </div>
          <div v-else class="radar-empty">{{ dashboard.radar.length ? '今日情绪数据为空' : '暂无雷达数据' }}</div>
          <p class="cap">六个维度越靠外越强；缩在虚线（50 分）以内的维度，就是当天明显的短板。</p>
        </el-card>

        <el-card shadow="never" class="dash-card">
          <div class="card-title">
            涨跌家数分布
          </div>
          <div class="dist-bars">
            <div v-for="b in distDisplay" :key="b.label" class="dist-col">
              <div class="dist-count">{{ b.count || '' }}</div>
              <div
                class="dist-bar"
                :class="distBarClass(b.dir)"
                :style="{ height: distHeight(b.count) + '%' }"
                :title="distTip(b)"
              />
              <div class="dist-label">{{ b.label }}</div>
            </div>
          </div>
          <div class="breadth-bar">
            <div class="breadth-track">
              <div class="breadth-up" :style="{ width: breadthUpW + '%' }" />
              <div class="breadth-flat" :style="{ width: breadthFlatW + '%' }" />
              <div class="breadth-down" :style="{ width: breadthDownW + '%' }" />
            </div>
            <div class="breadth-legend">
              <span class="lg-up">涨 {{ dashboard.breadth.up }}</span>
              <span class="lg-flat">平 {{ dashboard.breadth.flat }}</span>
              <span class="lg-down">跌 {{ dashboard.breadth.down }}</span>
            </div>
          </div>
          <div class="dist-foot">
            <span>涨跌 ≥3%：<b class="up">{{ dashboard.breadth.strong_up }}</b> 家强势 / <b class="down">{{ dashboard.breadth.strong_down }}</b> 家弱势</span>
            <span>平均 {{ fmtPct(dashboard.breadth.avg_pct) }} · 中位 {{ fmtPct(dashboard.breadth.median_pct) }}</span>
          </div>
          <p class="cap">右端（涨停/大涨）越长，赚钱效应越强；两端同时变长、中间变短 = 涨跌分化加剧，多数个股其实在原地。</p>
        </el-card>
      </div>
    </section>

    <!-- 市场温度与资金结构：把今天的读数放进近一年分位/趋势，回答「今天算热还是冷、钱去了哪」 -->
    <section v-if="metrics" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataAnalysis /></el-icon> 市场温度与资金结构</span>
        <span class="fresh-tag is-hist">分位=近一年历史</span>
        <span class="block-hint">
          {{ metrics.status_label || '已收盘' }}{{ metrics.is_live ? '（读数仍在跳动）' : '（当日数据已定）' }}
          <em v-if="metrics.as_of" class="data-time">数据 {{ metrics.as_of }} · 更新 {{ shortTime(metrics.updated) }}</em>
        </span>
      </div>

      <div v-if="metrics.alerts.length" class="alert-row">
        <span v-for="a in metrics.alerts" :key="a.title" class="alert-chip" :class="`is-${a.level}`">
          <b>{{ a.title }}</b><span>{{ a.detail }}</span>
        </span>
      </div>
      <div v-else-if="metrics.ready" class="alert-row alert-row--calm">
        <span class="alert-chip is-ok">无异常信号 · 温度与广度均在正常区间</span>
      </div>

      <!-- 温度分位：每项一条分位条，中位刻度固定在 50% -->
      <div class="temp-headline">
        今日读数 · 近一年分位
        <span class="dist-note">条越长越接近近一年极值；竖线 = 中位数（50% 分位）</span>
      </div>
      <div class="temp-grid">
        <div v-for="t in metrics.temperature" :key="t.key" class="temp-item" :title="t.desc">
          <div class="temp-head">
            <span class="temp-label">{{ t.label }}</span>
            <span class="temp-value">{{ t.value }}<em>{{ t.unit }}</em></span>
          </div>
          <div class="temp-track">
            <i v-if="t.rank != null" class="temp-fill" :class="rankTone(t)" :style="{ width: t.rank + '%' }" />
            <i class="temp-median" title="近一年中位数 = 50% 分位" />
          </div>
          <div class="temp-foot">
            <span v-if="t.rank != null">
              近一年 <b :class="rankTone(t)">{{ t.rank }}%</b> 分位
              <em v-if="!t.higher_is_hot" class="temp-rev">越高越冷</em>
            </span>
            <span v-else class="temp-pending">历史基线构建中…</span>
            <span v-if="t.median != null" class="temp-med">中位 {{ t.median }}{{ t.unit }}</span>
          </div>
        </div>
      </div>

      <!-- 市场宽度：60 日趋势，回答「涨跌是在扩散还是收敛」 -->
      <el-card shadow="never" class="dash-card width-card">
        <div class="card-title card-title--flex">
          市场宽度趋势
          <span class="dist-note">前 {{ breadthSeries.length - 1 }} 日 = 历史收盘</span>
          <div v-if="bwChart" class="bw-readout">
            <span class="ro ro--up">今日上涨率 <b>{{ bwChart.today.up_pct }}%</b></span>
            <span v-if="bwChart.today.ma20_above != null" class="ro ro--ma">
              站上 20 日线 <b>{{ bwChart.today.ma20_above }}%</b>
            </span>
            <span class="ro ro--med">一年中位 {{ bwChart.today.median }}%</span>
          </div>
        </div>
        <div v-if="bwChart" class="bw-plot">
          <div class="bw-yaxis">
            <span v-for="t in bwChart.yTicks" :key="t.v" :style="{ bottom: t.v + '%' }">{{ t.v }}%</span>
          </div>
          <div class="bw-canvas">
            <div
              v-for="t in bwChart.yTicks"
              :key="'g' + t.v"
              class="bw-gline"
              :class="{ 'is-mid': t.v === 50 }"
              :style="{ bottom: t.v + '%' }"
            />
            <svg class="bw-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <linearGradient :id="'bwFill'" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--el-color-primary)" stop-opacity="0.28" />
                  <stop offset="100%" stop-color="var(--el-color-primary)" stop-opacity="0.02" />
                </linearGradient>
              </defs>
              <polygon :points="bwChart.area" :fill="'url(#bwFill)'" />
              <polyline :points="bwChart.upLine" class="bw-up" vector-effect="non-scaling-stroke" />
              <polyline
                v-for="(seg, i) in bwChart.maSegs"
                :key="'ma' + i"
                :points="seg"
                class="bw-ma"
                vector-effect="non-scaling-stroke"
              />
            </svg>
            <!-- 今日竖线：标示曲线末端对应的交易日 -->
            <div class="bw-today" />
            <div
              v-for="d in bwChart.dots"
              :key="d.k"
              class="bw-pt"
              :style="{ left: d.xp + '%', bottom: d.yp + '%' }"
            >
              <span class="bw-tip">{{ d.tip }}</span>
            </div>
            <div
              v-for="l in bwChart.xTicks"
              :key="l.k"
              class="bw-xaxis"
              :style="{ left: l.xp + '%', transform: l.align }"
            >{{ l.text }}</div>
          </div>
        </div>
        <div v-else class="rank-empty">暂无足够交易日数据</div>
        <div class="bw-legend">
          <span class="bw-key"><i class="k-up" />上涨个股占比</span>
          <span class="bw-key"><i class="k-ma" />站上 20 日线占比</span>
          <span class="bw-key"><i class="k-mid" />50% 多空分界</span>
        </div>
        <p class="cap">
          上涨率高于 50% = 赚钱效应扩散到多数个股；连续多日低于 30% 说明下跌在扩散，指数再涨也可能只是少数权重在拉。
          站上 20 日线的比例代表中期趋势还在的个股有多少。
        </p>
      </el-card>

      <div class="mini-grid">
        <!-- 市值风格：全市场按流通市值三等分，比较各组平均涨跌幅 -->
        <el-card v-if="metrics.style" shadow="never" class="dash-card">
          <div class="card-title">
            市值风格：钱偏大还是偏小
            <span class="dist-note">
              市值分组按<template v-if="metrics.style.mv_as_of"> {{ metrics.style.mv_as_of }} </template>收盘流通市值
            </span>
          </div>
          <div v-if="styleVerdict" class="style-verdict" :class="`tone-${styleVerdict.tone}`">
            <b>{{ styleVerdict.label }}</b>
            <span>{{ styleVerdict.detail }}</span>
          </div>
          <div class="style-bars">
            <div v-for="b in metrics.style.buckets" :key="b.key" class="style-row">
              <span class="style-name">{{ b.label }}</span>
              <span class="style-count">{{ b.count }} 家</span>
              <div class="style-track">
                <i class="style-axis" />
                <i class="style-fill" :class="b.pct >= 0 ? 'is-up' : 'is-down'" :style="styleBar(b.pct)" />
              </div>
              <span class="style-val" :class="b.pct >= 0 ? 'up' : 'down'">{{ fmtPct(b.pct) }}</span>
            </div>
          </div>
          <p class="cap">
            三组是把同一批股票按流通市值从大到小排成三段（各约三分之一），比较各组今天平均涨跌幅。
            谁跌得少／涨得多，就说明资金更愿意待在那一边；横线是 0%，条在中线左侧为跌。
          </p>
        </el-card>

        <!-- 成交额集中度：头部吸金占比 + HHI -->
        <el-card v-if="metrics.concentration" shadow="never" class="dash-card">
          <div class="card-title">
            成交额集中度
            <span class="dist-note">HHI 越高，资金越集中在少数个股</span>
          </div>
          <div class="conc-bar">
            <div class="conc-seg conc-top" :style="{ width: concTopW + '%' }" :title="`前10名合计 ${metrics.concentration.top10_share}%`" />
            <div class="conc-seg conc-rest" />
          </div>
          <div class="conc-legend">
            <span class="lg-up">前10名 {{ metrics.concentration.top10_share }}%</span>
            <span class="lg-rest">其余 {{ (100 - metrics.concentration.top10_share).toFixed(1) }}%</span>
          </div>
          <div class="snap-row snap-row--tight">
            <div class="snap-item">
              <div class="snap-label">第一大占比</div>
              <div class="snap-value">{{ metrics.concentration.top1_share }}%</div>
            </div>
            <div class="snap-item">
              <div class="snap-label">HHI</div>
              <div class="snap-value">{{ metrics.concentration.hhi }}</div>
            </div>
          </div>
          <p class="cap">前 10 名占全市场成交额的比重越高，说明资金越集中、抱团少数标的，其余个股越缺流动性。</p>
        </el-card>
      </div>
    </section>
    </section>

    <!-- 04 事件与类比：只回答「会不会改变判断」+ 今日买卖清单 -->
    <section id="events" class="mr-sec">
      <div class="mr-sec-head">
        <span class="mr-sec-no">04</span>
        <span class="mr-sec-title">事件与类比</span>
        <span class="mr-sec-hint">{{ eventHeadline || '只保留会改变判断的事件' }} · 历史类比看「像今天这样的环境后来怎么走」</span>
        <span class="mr-sec-actions">
          <span v-if="eventsData?.updated" class="data-time">更新 {{ shortTime(eventsData.updated) }}</span>
        </span>
      </div>

      <div v-if="eventsLoading && !eventsData" class="ev-empty">
        <el-icon class="is-loading"><Loading /></el-icon> 正在加载今日事件…
      </div>
      <div v-else-if="!eventsData" class="ev-empty">事件源暂不可用，不影响 01 今日结论与 02 当前位置</div>

      <div v-if="events.length" class="ev-list">
        <el-card
          v-for="e in events"
          :key="e.id"
          shadow="never"
          class="ev-card"
          :class="[`impact-${e.impact}`, { 'is-expired': e.status === 'expired' }]"
        >
          <div class="ev-row ev-main">
            <span class="ev-time">{{ e.time }}</span>
            <span class="ev-title">{{ e.title }}</span>
            <span v-if="e.surprise_label" class="ev-surprise" :class="surpriseClass(e)">
              {{ e.surprise_label }}
            </span>
            <span class="ev-status" :class="`status-${e.status}`">{{ eventStatusLabel(e) }}</span>
            <span class="ev-toggle" @click="toggleEvent(e.id)">
              {{ expandedEvents.includes(e.id) ? '收起' : '展开' }}
            </span>
          </div>

          <div class="ev-row ev-impact">
            <span class="ev-label">影响</span>
            <span class="ev-impact-val" :class="`dir-${e.direction}`">{{ impactText(e) }}</span>
          </div>

          <div v-if="e.action" class="ev-row ev-action">
            <span class="ev-label">怎么做</span>
            <span>{{ e.action }}</span>
          </div>

          <div v-if="e.sectors && e.sectors.length" class="ev-row ev-sectors">
            <span class="ev-label">相关</span>
            <span v-for="s in e.sectors" :key="s" class="ev-tag">{{ s }}</span>
          </div>

          <div v-if="expandedEvents.includes(e.id)" class="ev-detail">
            <div v-if="e.transmission && e.transmission.length" class="ev-trans">
              <span v-for="(t, i) in e.transmission" :key="i" class="ev-trans-step">
                {{ t }}<em v-if="i < e.transmission.length - 1">→</em>
              </span>
            </div>
            <div v-if="e.watch" class="ev-watch">观察点：{{ e.watch }}</div>
          </div>
        </el-card>
      </div>
      <div v-else-if="eventsData && !eventsData.source_ok" class="ev-empty">
        经济日历暂不可用，事件影响暂缺；不影响 01 今日结论
      </div>
      <div v-else-if="eventsData" class="ev-empty">今日无重大宏观事件，按原计划执行</div>

      <!-- 历史类比：在热度分位空间找最像今天的交易日，看其后 20 日实际表现 -->
      <section v-if="position?.analogs" class="pos-analog">
        <div class="pos-analog-head">
          <span class="pos-analog-title"><el-icon><DataLine /></el-icon> 历史类比</span>
          <span class="dist-note">{{ position.analogs.metric }} · 相邻样本间隔 ≥30 个交易日</span>
        </div>
        <div class="pos-analog-summary">
          <span>
            最像今天的 {{ position.analogs.n }} 个交易日，其后 {{ position.analogs.day }} 日
            <b class="mono" :class="clsByVal(position.analogs.median_return)">
              中位 {{ signedPct(position.analogs.median_return) }}
            </b>
            <b class="mono">上涨 {{ position.analogs.win_rate == null ? '—' : position.analogs.win_rate + '%' }}</b>
          </span>
        </div>
        <div class="pos-analog-grid">
          <div v-for="c in position.analogs.cases" :key="c.date" class="pos-analog-case">
            <span class="pos-analog-date">{{ c.date }}</span>
            <span class="pos-analog-sim">相似度 {{ c.similarity }}%</span>
            <span class="mono" :class="clsByVal(c.forward_return)">后 {{ position.analogs.day }} 日 {{ signedPct(c.forward_return) }}</span>
            <span class="pos-analog-comp mono">当时分位 {{ c.composite ?? '—' }}%</span>
          </div>
        </div>
        <p class="cap">{{ position.analogs.note }}</p>
      </section>

      <!-- 今日买卖清单：盘中实时计算，与 AI 文字研判相互独立 -->
      <section v-if="syn" class="syn-guide">
        <div class="syn-guide-head">
          <span class="syn-guide-title"><el-icon><TrendCharts /></el-icon> 今日买卖清单</span>
          <span class="syn-guide-hint">盘中实时计算 · 与 01 的文字结论相互独立</span>
        </div>
        <div class="syn-guide-grid">
          <div class="syn-guide-col">
            <div class="syn-guide-col-head">
              <span class="buy">买入关注</span>
              <span class="syn-guide-count">{{ buyList.length }} 只</span>
            </div>
            <div v-for="b in buyList" :key="'b-' + b.code" class="syn-guide-item">
              <div class="syn-guide-row">
                <router-link target="_blank" rel="noopener" :to="`/stocks/${b.code}`" class="syn-guide-name">{{ b.name || b.code }}</router-link>
                <span class="syn-guide-code">{{ b.code }}</span>
                <el-tag size="small" :type="buyTagType(b)" effect="plain">{{ buyStateLabel(b) }}</el-tag>
              </div>
              <div class="syn-guide-metrics">
                <span>现价 <b class="mono">{{ fmtPrice(b.last_price) }}</b></span>
                <span>触发价 <b class="mono">{{ fmtPrice(b.trigger_price) }}</b></span>
                <span v-if="b.distance_pct != null" :class="{ 'is-near': isNear(b.distance_pct) }">
                  偏离 <b class="mono">{{ fmtPct(b.distance_pct) }}</b>
                </span>
              </div>
              <div class="syn-guide-advice">{{ b.advice || '等待实时价确认触发' }}</div>
            </div>
            <div v-if="!buyList.length" class="syn-guide-empty">暂无待触发的买入计划</div>
          </div>

          <div class="syn-guide-col">
            <div class="syn-guide-col-head">
              <span class="sell">持仓卖出</span>
              <span class="syn-guide-count">{{ sellList.length }} 只</span>
            </div>
            <div v-for="s in sellList" :key="'s-' + s.code" class="syn-guide-item">
              <div class="syn-guide-row">
                <router-link target="_blank" rel="noopener" :to="`/stocks/${s.code}`" class="syn-guide-name">{{ s.name || s.code }}</router-link>
                <span class="syn-guide-code">{{ s.code }}</span>
                <el-tag size="small" :type="sellTagType(s)" effect="plain">{{ s.advice_label || s.advice || '持有' }}</el-tag>
              </div>
              <div class="syn-guide-metrics">
                <span>现价 <b class="mono">{{ fmtPrice(s.last_price) }}</b></span>
                <span>持仓 <b class="mono">{{ s.quantity ?? '—' }}</b></span>
                <span v-if="s.profit_loss_rate != null" :class="clsByVal(s.profit_loss_rate)">
                  盈亏 <b class="mono">{{ fmtPct(s.profit_loss_rate) }}</b>
                </span>
              </div>
              <div class="syn-guide-advice">{{ s.advice_text || s.advice || '暂无卖出动作' }}</div>
            </div>
            <div v-if="!sellList.length" class="syn-guide-empty">暂无持仓卖出建议</div>
          </div>
        </div>
      </section>
    </section>

    <!-- 05 推理过程：默认收起，需要复盘判断依据时展开 -->
    <section v-if="verdict" id="reason" class="mr-sec">
      <div class="mr-sec-head">
        <span class="mr-sec-no">05</span>
        <span class="mr-sec-title">推理过程</span>
        <span class="mr-sec-hint">{{ reasonSections }}</span>
      </div>

      <el-collapse v-model="reasonOpen" class="syn-reason">
        <el-collapse-item name="reason">
          <template #title>
            <span class="syn-reason-title"><el-icon><Document /></el-icon> 展开推理过程</span>
            <span class="syn-reason-sub">{{ reasonSections || '现状 · 原因 · 观察 · 策略 · 风险' }}</span>
          </template>

          <div class="syn-reason-body">
            <div v-if="verdict.status" class="syn-panel">
              <div class="syn-panel-title status"><el-icon><DataLine /></el-icon> 现状</div>
              <div class="syn-plain-text">{{ verdict.status }}</div>
            </div>

            <div v-if="verdict.reasons.length" class="syn-panel">
              <div class="syn-panel-title reasons"><el-icon><InfoFilled /></el-icon> 引起现状的原因</div>
              <ul class="syn-panel-list">
                <li v-for="(r, i) in verdict.reasons" :key="'r' + i">▸ {{ r }}</li>
              </ul>
            </div>

            <div v-if="verdict.external_observation || verdict.watch.length" class="syn-panel">
              <div class="syn-panel-title watch"><el-icon><View /></el-icon> 今日观察</div>
              <div v-if="verdict.external_observation" class="syn-ext">
                <div class="syn-ext-label">外围传导 · 美股 / 大宗商品 → A股情绪</div>
                <div class="syn-ext-text">{{ verdict.external_observation }}</div>
              </div>
              <ul v-if="verdict.watch.length" class="syn-panel-list">
                <li v-for="(w, i) in verdict.watch" :key="'w' + i">◎ {{ w }}</li>
              </ul>
            </div>

            <div v-if="verdict.strategy" class="syn-panel">
              <div class="syn-panel-title strat"><el-icon><Guide /></el-icon> 操作策略</div>
              <div class="syn-strat-text">{{ verdict.strategy }}</div>
            </div>

            <div v-if="verdict.extra.length" class="syn-panel">
              <div class="syn-panel-title extra"><el-icon><StarFilled /></el-icon> 重点补充</div>
              <ul class="syn-panel-list">
                <li v-for="(e, i) in verdict.extra" :key="'e' + i">★ {{ e }}</li>
              </ul>
            </div>

            <div v-if="verdict.risk_tips.length" class="syn-risk">
              <span class="syn-risk-title"><el-icon><WarnTriangleFilled /></el-icon> 风险提示</span>
              <ul class="syn-risk-list">
                <li v-for="(tip, i) in verdict.risk_tips" :key="i">{{ tip }}</li>
              </ul>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </section>

    <!-- 免责声明 -->
    <p class="disclaimer">以上数据来自公开源，AI 研判仅供参考，不构成投资建议</p>
  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'MarketReview' })
import { ref, computed, onMounted, onActivated, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  DataLine,
  Refresh,
  Loading,
  Histogram,
  QuestionFilled,
  TrendCharts,
  Document,
  InfoFilled,
  StarFilled,
  View,
  Guide,
  WarnTriangleFilled,
} from '@element-plus/icons-vue'
import {
  vibeApi,
  type IndexQuote,
  type MarketDashboard,
  type MarketEvent,
  type MarketEvents,
  type MarketMetrics,
  type MarketPosition,
  type MarketPositionMetric,
  type MarketSynthesis,
  type MarketTemperatureItem,
  type PreOpen,
  type PreOpenBand,
  type SynthesisBuyItem,
  type SynthesisSellItem,
} from '@/api/vibe'
import { fmtPrice, fmtPct, fmtAbsPct, fmtSigned, clsByVal } from '@/utils/format'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'
import { use as echartsUse } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

echartsUse([CanvasRenderer, LineChart, GridComponent, TooltipComponent, MarkLineComponent])

const route = useRoute()
const loading = ref(false)
const indices = ref<IndexQuote[]>([])
const dashboard = ref<MarketDashboard | null>(null)
const metrics = ref<MarketMetrics | null>(null)

const shortTime = (v?: string | null) =>
  v ? formatBeijingDateTimeMinute(String(v)).slice(5, 16) : ''

// ── 01 今日结论：综合研判（AI / 规则兜底），页头「AI 重新研判」唯一入口 ──
const syn = ref<MarketSynthesis | null>(null)
const synLoading = ref(false)

async function loadSynthesis(refresh = false) {
  synLoading.value = true
  try {
    // 默认走市场级缓存（秒开）；仅「AI 重新研判」传 refresh=true 强制重算
    const res = await vibeApi.getSynthesis(refresh)
    syn.value = res || null
  } catch (e: any) {
    console.error('[MarketReview] 综合研判加载失败', e)
    ElMessage.error(e?.message || '综合研判加载失败，请稍后重试')
  } finally {
    synLoading.value = false
  }
}

// ── 02 当前位置：近 10 年历史分位（估值 / 情绪 / 宽度 / 资金） ──
const position = ref<MarketPosition | null>(null)
const positionLoading = ref(false)
let positionRetryTimer: number | undefined

async function loadPosition(refresh = false) {
  positionLoading.value = true
  try {
    const res = await vibeApi.getMarketPosition(refresh)
    position.value = res
    // 基线仍在后台构建：40s 后再试一次，避免用户手动刷新
    if (!res?.ready) schedulePositionRetry()
  } catch (e: any) {
    console.warn('[MarketReview] 大盘位置加载失败', e?.message || e)
  } finally {
    positionLoading.value = false
  }
}

function schedulePositionRetry() {
  if (positionRetryTimer) return
  positionRetryTimer = window.setTimeout(() => {
    positionRetryTimer = undefined
    if (!position.value?.ready) loadPosition(false)
  }, 40000)
}

/** 分位配色：高位偏热、低位偏冷（仅用于分位条，不用于涨跌） */
const posTone = (pct?: number | null) =>
  pct == null ? 'is-muted' : pct >= 75 ? 'is-hot' : pct <= 25 ? 'is-cold' : 'is-neutral'

/** 位置指标分组顺序 + 每组一句话解释 */
const POSITION_GROUP_HINTS: Record<string, string> = {
  估值: '贵不贵',
  位置: '指数自身的高低',
  情绪: '日内博弈与稳定性',
  参与度: '资金与广度',
  底部特征: '熊市末期特征',
}

const positionGroups = computed(() => {
  const list = position.value?.position || []
  const order = Object.keys(POSITION_GROUP_HINTS)
  const rank = (s: string) => (order.indexOf(s) < 0 ? 99 : order.indexOf(s))
  return [...new Set(list.map(m => m.group))]
    .map(g => ({ group: g, hint: POSITION_GROUP_HINTS[g] || '', items: list.filter(m => m.group === g) }))
    .sort((a, b) => rank(a.group) - rank(b.group))
})

/** 逃顶 / 判断底部：后端整理的判据 + 历史证据 */
const posGuides = computed(() => {
  const g = position.value?.guidance
  return g ? [g.top, g.bottom] : []
})

/** 反向指标（越高越冷）取热度分位，仅用于配色 */
const heatOfMetric = (m: MarketPositionMetric) =>
  m.percentile == null ? null : (m.higher_is_hot ? m.percentile : 100 - m.percentile)

// 位置标尺：五档分区（0–100 各占 20 分位）+ 刻度
const GAUGE_BANDS = [
  { key: 'oversold', name: '判底', width: 20 },
  { key: 'cool', name: '偏冷', width: 20 },
  { key: 'neutral', name: '中位', width: 20 },
  { key: 'warm', name: '偏热', width: 20 },
  { key: 'overheated', name: '逃顶', width: 20 },
]
const GAUGE_TICKS = [0, 20, 40, 60, 80, 100]

/** 指标简称（标尺刻点与内部结构 chips 用） */
const POSITION_SHORT: Record<string, string> = {
  drawdown: '回撤',
  ma250_dev: '年线偏离',
  amplitude: '振幅',
  volatility: '波动率',
  amount: '成交额',
  up_pct: '上涨家数',
  low_price: '低价股',
  valuation_pe: 'PE',
  valuation_pb: 'PB',
}

const compositePct = computed(() => position.value?.composite.percentile ?? null)

/** 参与合成的指标：折算成热度分位后的刻点（标尺上的小圆点） */
const heatDots = computed(() => {
  const list = (position.value?.position || []).filter(m => m.in_composite && m.percentile != null)
  return list.map((m, i) => {
    const pct = heatOfMetric(m) as number
    return {
      key: m.key,
      label: POSITION_SHORT[m.key] || m.label,
      pct,
      tone: posTone(pct),
      row: i % 2 === 1,
    }
  })
})

/** 参与合成的指标按热度从高到低排列（内部结构 chips） */
const componentHeat = computed(() =>
  (position.value?.position || [])
    .filter(m => m.in_composite && m.percentile != null)
    .map(m => ({
      key: m.key,
      label: POSITION_SHORT[m.key] || m.label,
      pct: heatOfMetric(m) as number,
      tone: posTone(heatOfMetric(m)),
    }))
    .sort((a, b) => b.pct - a.pct),
)

/** 内部高度分化时给一句话解释：为什么合成分位不高不低 */
const heatSpread = computed(() => {
  const c = componentHeat.value
  if (c.length < 2) return null
  const hot = c[0]
  const cold = c[c.length - 1]
  const gap = hot.pct - cold.pct
  if (gap < 40) return null
  const tail = position.value?.composite.zone === 'neutral'
    ? '两端相互抵消，合成值落在中位区，所以现在既不像顶、也不像底'
    : '合成值由多数指标决定，极端项需结合下方单项指标判断'
  return {
    hot,
    cold,
    gap,
    text: `内部高度分化：${hot.label} ${hot.pct}%（最热）与 ${cold.label} ${cold.pct}%（最冷）相差 ${gap} 个分位，${tail}`,
  }
})

/** 现在离顶 / 离底有多远（按后端阈值计算） */
const posDistance = computed(() => {
  const pct = compositePct.value
  if (pct == null) return []
  const th = position.value?.composite.thresholds || { top: 80, bottom: 20 }
  return [
    pct >= th.top
      ? { key: 'top', text: `已进入逃顶区（≥${th.top}）`, tone: 'is-hot' }
      : { key: 'top', text: `距逃顶区还有 ${th.top - pct} 个分位`, tone: 'is-neutral' },
    pct <= th.bottom
      ? { key: 'bottom', text: `已进入判底观察区（≤${th.bottom}）`, tone: 'is-cold' }
      : { key: 'bottom', text: `距判底区还有 ${pct - th.bottom} 个分位`, tone: 'is-neutral' },
  ]
})

/** 一句话判定：现在到底是顶、底，还是都不是 */
const posVerdict = computed(() => {
  const pct = compositePct.value
  const zone = position.value?.composite.zone
  const yrs = position.value?.window_years ?? 10
  if (pct == null) return { title: '暂无合成分位', sub: '历史样本不足，先看下方单项指标' }
  if (zone === 'overheated') {
    return { title: '接近顶部（逃顶信号区）', sub: `合成分位 ${pct}%，多数指标处于近 ${yrs} 年最热 20%；追高赔率下降` }
  }
  if (zone === 'warm') {
    return { title: '偏高但还不是顶', sub: `合成分位 ${pct}%，位于偏热区（60–80）；持仓为主，新增仓位等回踩确认` }
  }
  if (zone === 'cool') {
    return { title: '偏低但还不是底', sub: `合成分位 ${pct}%，位于偏冷区（20–40）；关注修复信号，不急着抢跑` }
  }
  if (zone === 'oversold') {
    return { title: '接近底部（判底观察区）', sub: `合成分位 ${pct}%，多项指标处于近 ${yrs} 年最冷 20%；等宽度回升与波动率回落再分批建仓` }
  }
  return {
    title: '既不是顶，也不是底',
    sub: `合成分位 ${pct}%，落在中位区（40–60）；位置层面不做加减仓，跟随趋势与事件交易`,
  }
})

/** 近 10 年合成分位走势（标线：80 逃顶 / 20 判底） */
const compositeChartOption = computed<EChartsOption | null>(() => {
  const pts = position.value?.composite.series || []
  if (pts.length < 2) return null
  const th = position.value?.composite.thresholds || { top: 80, bottom: 20 }
  const option: EChartsOption = {
    grid: { left: 6, right: 46, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      formatter: (p: any) => {
        const it = Array.isArray(p) ? p[0] : p
        return `${it?.axisValue ?? ''}<br/>合成分位 <b>${it?.value ?? '—'}%</b>`
      },
    },
    xAxis: {
      type: 'category',
      data: pts.map(p => p.date),
      boundaryGap: false,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
      axisLabel: {
        fontSize: 11,
        color: '#9aa0a6',
        hideOverlap: true,
        formatter: (v: string) => String(v).slice(2),
      },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 20,
      axisLabel: { fontSize: 11, color: '#9aa0a6' },
      splitLine: { lineStyle: { color: '#f0f1f3' } },
    },
    series: [
      {
        type: 'line',
        name: '合成分位',
        data: pts.map(p => p.pct),
        showSymbol: false,
        smooth: 0.2,
        lineStyle: { width: 1.6, color: '#2b6cb0' },
        areaStyle: { color: 'rgba(43,108,176,.10)' },
        itemStyle: { color: '#2b6cb0' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              yAxis: th.top,
              name: `逃顶 ${th.top}`,
              lineStyle: { color: 'rgba(245,108,108,.75)', type: 'dashed', width: 1 },
              label: { position: 'end', formatter: `逃顶 ${th.top}`, color: '#f56c6c', fontSize: 10 },
            },
            {
              yAxis: th.bottom,
              name: `判底 ${th.bottom}`,
              lineStyle: { color: 'rgba(103,194,58,.75)', type: 'dashed', width: 1 },
              label: { position: 'end', formatter: `判底 ${th.bottom}`, color: '#67c23a', fontSize: 10 },
            },
          ],
        },
      },
    ],
  }
  return option
})

/** 未来收益发散条：以 0 为中轴，按最大绝对值归一化 */
const maxAbsFwd = computed(() => {
  const bins = position.value?.forward?.bins || []
  return Math.max(1, ...bins.map(b => Math.abs(b.median_return || 0)))
})

function fwdBarStyle(med: number | null): Record<string, string> {
  if (med == null) return { display: 'none' }
  const w = Math.max(2, Math.min(50, (Math.abs(med) / maxAbsFwd.value) * 50))
  return med >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }
}

const scrollTo = (id: string) =>
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

// ── 开盘情景：隔夜外盘定档开盘缺口 + 上一交易日情绪结构（盘前唯一的前瞻信息） ──
const preOpen = ref<PreOpen | null>(null)
const preOpenLoading = ref(false)
const preOpenOpen = ref(isPreOpenWindow())

function isPreOpenWindow(): boolean {
  // 北京时间 08:30–09:25 自动展开；其余时段默认收起，避免干扰盘中/收盘复盘
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date())
  const val = (t: string) => Number(parts.find(p => p.type === t)?.value || 0)
  const hm = val('hour') * 60 + val('minute')
  return hm >= 8 * 60 + 30 && hm <= 9 * 60 + 25
}

/** 盘前窗口（08:30–09:25）：只在这段时间展示「开盘情景」这类前瞻块 */
const isPreOpen = computed(() => isPreOpenWindow())

async function loadPreOpen(refresh = false) {
  preOpenLoading.value = true
  try {
    const res = await vibeApi.getPreOpen(refresh)
    preOpen.value = (res as any).data || null
  } catch (e: any) {
    // 盘前块是增强信息，失败不打断看板主数据
    console.warn('[Overview] 开盘情景加载失败:', e?.message || e)
  } finally {
    preOpenLoading.value = false
  }
}

const signedPct = (v?: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const deltaText = (v?: number | null, unit = '') =>
  v == null || v === 0 ? '' : `${v > 0 ? '+' : ''}${v}${unit}`
const deltaClass = (v?: number | null) => (v == null || v === 0 ? 'flat' : v > 0 ? 'up' : 'down')
const bandRange = (b: PreOpenBand) => {
  if (b.lo == null) return `≤ ${b.hi}%`
  if (b.hi == null) return `≥ ${b.lo}%`
  return `${b.lo} ~ ${b.hi}%`
}

// 指针位置：把 -1.5%~+1.5% 线性映射到 0~100%，与刻度区间的成比例宽度对齐
const scenarioPointerPct = computed(() => {
  const pct = preOpen.value?.gap.pct
  if (pct == null) return null
  const raw = ((Math.max(-1.5, Math.min(1.5, pct)) + 1.5) / 3) * 100
  return Math.min(97, Math.max(3, raw))
})

// 标题日期：优先后端数据返回的交易日；数据未回前用轻量接口预取的最新交易日（首屏即正确，不闪非交易日当天）
const tradeDate = ref('')
const titleDate = computed(() => dashboard.value?.trade_date || tradeDate.value || '')

// 页头「更新于」：展示看板数据的生成时刻
const updatedAt = computed(() =>
  dashboard.value?.updated ? formatBeijingDateTimeMinute(dashboard.value.updated) : ''
)

// 数据时点：与「抓取时刻」分开，避免把周末刷新当成数据新鲜
const dataAsOf = computed(() => {
  const a = dashboard.value?.as_of
  if (!a) return ''
  const s = String(a)
  return s.length >= 16 ? s.slice(5, 16) : s
})

// 标题星期：让用户一眼确认是不是交易日当天
const weekday = computed(() => {
  const d = titleDate.value
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return ''
  const dt = new Date(`${d}T00:00:00+08:00`)
  return `周${'日一二三四五六'[dt.getDay()]}`
})

// 盘中 / 休市：同一份数据在收盘后看到，语义完全不同
function beijingClock() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date())
  const val = (t: string) => parts.find(p => p.type === t)?.value || ''
  return { wd: val('weekday'), hm: Number(val('hour')) * 60 + Number(val('minute')) }
}
const marketState = computed(() => {
  const { wd, hm } = beijingClock()
  const weekdayOk = wd !== 'Sat' && wd !== 'Sun'
  const trading = (hm >= 570 && hm <= 690) || (hm >= 780 && hm <= 900)
  return weekdayOk && trading
    ? { label: '盘中', cls: 'is-open' }
    : { label: '休市', cls: 'is-closed' }
})

// ── 04 事件与类比：四行固定结构（时间+事件 / 影响 / 怎么做 / 相关） ──
const eventsData = ref<MarketEvents | null>(null)
const eventsLoading = ref(false)
const events = computed<MarketEvent[]>(() => eventsData.value?.events || [])
const expandedEvents = ref<string[]>([])
const toggleEvent = (id: string) => {
  const i = expandedEvents.value.indexOf(id)
  if (i >= 0) expandedEvents.value.splice(i, 1)
  else expandedEvents.value.push(id)
}
const shortTitle = (t: string) => (t && t.length > 14 ? `${t.slice(0, 14)}…` : t || '')
const dirLabel = (d?: string) => (d === 'bull' ? '偏多' : d === 'bear' ? '偏空' : '中性')
const surpriseClass = (e: MarketEvent) => `sur-${e.direction || 'neutral'}`
const eventStatusLabel = (e: MarketEvent) =>
  e.status === 'pending' ? '待公布' : e.status === 'expired' ? '已过时' : '已公布'

/** 影响一行说清三件事：方向 / 力度 / 时效；噪音事件明确标注「不改判断」 */
const impactText = (e: MarketEvent) => {
  if (e.impact === 'none') return '无影响 · 不改判断'
  const parts = [dirLabel(e.direction)]
  if (e.strength) parts.push(e.strength)
  if (e.horizon) parts.push(e.horizon)
  return parts.join(' · ')
}

/** 区块标题：件数 + 其中真正会改变方向的件数（让用户知道要不要逐条读） */
const eventHeadline = computed(() => {
  const list = events.value
  if (!list.length) return ''
  const dir = list.filter(e => e.impact === 'direction').length
  const vol = list.filter(e => e.impact === 'volatility').length
  if (dir) return `共 ${list.length} 件 · ${dir} 件可能改变方向`
  if (vol) return `共 ${list.length} 件 · 仅影响 ${vol} 次盘中波动`
  return `共 ${list.length} 件 · 均不改变判断`
})

async function loadEvents() {
  eventsLoading.value = true
  try {
    const res: any = await vibeApi.getMarketEvents()
    eventsData.value = res?.data || res || null
  } catch (e: any) {
    console.warn('[MarketReview] 事件加载失败', e?.message || e)
  } finally {
    eventsLoading.value = false
  }
  scrollToEventsIfNeeded()
}

// 深链 /vibe/market#events：事件块要等数据回来才渲染，数据到位后补一次定位
const scrollToEventsIfNeeded = () => {
  if (route.hash !== '#events' || !eventsData.value) return
  requestAnimationFrame(() => scrollTo('events'))
}

const colorClass = (v: number | null | undefined) => {
  if (v == null) return 'flat'
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return 'flat'
}

// ---- 看板辅助函数 ----
const scoreColor = (v: number) => {
  if (v >= 70) return '#F04438'
  if (v >= 55) return '#FB923C'
  if (v >= 45) return '#F59E0B'
  if (v >= 30) return '#84CC16'
  return '#12B76A'
}
const scoreHex = computed(() => scoreColor(dashboard.value?.emotion.score ?? 50))

// ── 01 今日结论：把后端研判整理成「方向 / 信心度 / 结论 / 主攻·回避·仓位」 ──
const verdict = computed(() => {
  const v = syn.value?.verdict
  if (!v) return null
  const dir = v.direction || '中性'
  let dirClass = 'neutral'
  if (dir.includes('多') && !dir.includes('中性')) dirClass = 'bull'
  else if (dir.includes('空')) dirClass = 'bear'
  const conf = v.confidence != null ? Math.max(0, Math.min(100, Number(v.confidence))) : null
  const op = v.operation_points || {}
  return {
    direction: dir,
    directionZh: dirClass === 'bull' ? '偏多' : dirClass === 'bear' ? '偏空' : '中性',
    dirClass,
    confidence: conf,
    conclusion: v.conclusion || '',
    status: v.status || '',
    reasons: Array.isArray(v.reasons) ? v.reasons : [],
    operation_points: {
      main_direction: op.main_direction || '',
      avoid_direction: op.avoid_direction || '',
      position_discipline: op.position_discipline || '',
    },
    external_observation: v.external_observation || '',
    strategy: v.strategy || '',
    watch: Array.isArray(v.watch) ? v.watch : [],
    risk_tips: Array.isArray(v.risk_tips) ? v.risk_tips : [],
    extra: Array.isArray(v.extra) ? v.extra : [],
  }
})

/** 操作要点是否有内容可展示 */
const hasOperationPoints = computed(() => {
  const op = verdict.value?.operation_points
  if (!op) return false
  return !!(op.main_direction || op.avoid_direction || op.position_discipline)
})

/** 05 推理过程默认收起；展开后保留用户选择（keep-alive 切回仍在展开态） */
const reasonOpen = ref<string[]>([])

/** 折叠标题右侧：提示里面有哪些小节，避免用户不知道展开能看到什么 */
const reasonSections = computed(() => {
  const v = verdict.value
  if (!v) return ''
  const names: string[] = []
  if (v.status) names.push('现状')
  if (v.reasons.length) names.push('原因')
  if (v.external_observation || v.watch.length) names.push('今日观察')
  if (v.strategy) names.push('操作策略')
  if (v.extra.length) names.push('重点补充')
  if (v.risk_tips.length) names.push('风险提示')
  return names.join(' · ')
})

/** 结论横幅信心度环：--pct 与 --ring-color 由方向色驱动 */
const confRingStyle = computed(() => {
  const v = verdict.value
  const c = v?.confidence
  const color = v?.dirClass === 'bull' ? '#f56c6c' : v?.dirClass === 'bear' ? '#67c23a' : '#2b6cb0'
  return { '--pct': `${c != null ? c : 0}%`, '--ring-color': color }
})

/** 买卖清单（盘中实时计算，与 AI 文字研判相互独立） */
const buyList = computed<SynthesisBuyItem[]>(() => syn.value?.buys || [])
const sellList = computed<SynthesisSellItem[]>(() => syn.value?.sells || [])

const isNear = (dist: number) => dist <= 2

const buyStateLabel = (b: SynthesisBuyItem) => {
  if (b.triggered) return '已触发'
  if (b.confirmed === false) return '待确认'
  if (b.distance_pct != null && b.distance_pct <= 2) return '接近触发'
  return '等待回落'
}
type TagType = 'danger' | 'warning' | 'info' | 'success'
const buyTagType = (b: SynthesisBuyItem): TagType => {
  if (b.triggered) return 'danger'
  if (b.confirmed === false) return 'info'
  return b.distance_pct != null && b.distance_pct <= 2 ? 'warning' : 'info'
}
const sellTagType = (s: SynthesisSellItem): TagType => {
  const text = `${s.advice_label || ''}${s.advice || ''}`
  if (/清仓|止损|离场/.test(text)) return 'danger'
  if (/减仓|止盈/.test(text)) return 'warning'
  return /持有/.test(text) ? 'success' : 'info'
}

// 涨跌分布两端口径：与短线情绪页同源时不额外解释，仅降级时提示
const limitNote = computed(() =>
  dashboard.value?.limit?.source === 'threshold'
    ? '封板池暂不可用 · 涨停/跌停按涨跌幅阈值近似'
    : '涨停/跌停取封板池，与「短线情绪」页一致'
)

// 雷达图几何
const RADAR_CX = 120
const RADAR_CY = 120
const RADAR_MAX_R = 78

// 各维度说明（悬停提示）
const RADAR_DESC: Record<string, string> = {
  index: '主要指数当日平均涨跌幅所反映的大盘整体强度',
  profit: '赚钱效应：上涨家数占比、涨跌幅均值/中位数与强势股占比综合',
  money: '量能：全市场平均换手率与高换手个股占比，反映资金活跃度',
  speculation: '投机：涨停家数、封板率、最高连板与2板以上家数综合',
  resilience: '抗跌：下跌家数占比与大跌家数占比越低，抗跌分越高',
  mainline: '主线：领涨行业平均涨幅与覆盖度，反映资金主攻方向',
}

const radarPoints = computed(() => {
  const dims = dashboard.value?.radar || []
  return dims.map((r, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / dims.length
    const radius = (RADAR_MAX_R * Math.max(0, Math.min(100, r.value))) / 100
    return {
      key: r.key,
      label: r.label,
      value: r.value,
      desc: RADAR_DESC[r.key] || '',
      x: RADAR_CX + Math.cos(angle) * radius,
      y: RADAR_CY + Math.sin(angle) * radius,
      lx: RADAR_CX + Math.cos(angle) * (RADAR_MAX_R + 27),
      ly: RADAR_CY + Math.sin(angle) * (RADAR_MAX_R + 27),
      gx: RADAR_CX + Math.cos(angle) * RADAR_MAX_R,
      gy: RADAR_CY + Math.sin(angle) * RADAR_MAX_R,
    }
  })
})
const radarPolygon = computed(() =>
  radarPoints.value.map(p => `${p.x},${p.y}`).join(' ')
)
// 50 分中性基准环：与数据多边形同一套角度，便于直接比较「是否达标」
const radarMidPolygon = computed(() => {
  const n = dashboard.value?.radar?.length || 0
  if (!n) return ''
  return Array.from({ length: n }, (_, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / n
    const r = RADAR_MAX_R * 0.5
    return `${RADAR_CX + Math.cos(angle) * r},${RADAR_CY + Math.sin(angle) * r}`
  }).join(' ')
})
const radarGrid = computed(() => {
  const n = dashboard.value?.radar?.length || 0
  return [1, 0.66, 0.33].map((level, idx) => ({
    level,
    idx,
    points: Array.from({ length: n }, (_, i) => {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / n
      return `${RADAR_CX + Math.cos(angle) * RADAR_MAX_R * level},${RADAR_CY + Math.sin(angle) * RADAR_MAX_R * level}`
    }).join(' '),
  }))
})

// 涨跌分布
const distMax = computed(() =>
  Math.max(...(dashboard.value?.distribution.map(d => d.count) || [0]), 1)
)
const distHeight = (count: number) =>
  count <= 0 ? 0 : Math.max(4, (count / distMax.value) * 86)

// 反转后端分布（跌→涨）为 涨→平→跌，使红色(涨)在左、绿色(跌)在右，与广度条一致
const distDisplay = computed(() => {
  const dist = dashboard.value?.distribution || []
  return dist.slice().reverse()
})
const distBarClass = (dir: -1 | 0 | 1 | undefined) => {
  if (dir === 0) return 'dist-flat'
  if (dir === 1) return 'dist-up'
  return 'dist-down'
}

// 涨跌分布 tooltip：标注两端口径来源（封板池 / 阈值近似）
const distTip = (b: { label: string; count: number }) => {
  const note = (b.label === '涨停' || b.label === '跌停')
    ? (dashboard.value?.limit?.source === 'threshold'
      ? '（按涨跌幅阈值近似，含接近未封死）'
      : '（封板池口径，与短线情绪页一致）')
    : ''
  return `${b.label}: ${b.count}只${note}`
}

const breadthUpW = computed(() => {
  const b = dashboard.value?.breadth
  if (!b || !b.total) return 0
  return (b.up / b.total) * 100
})
const breadthFlatW = computed(() => {
  const b = dashboard.value?.breadth
  if (!b || !b.total) return 0
  return Math.max(0, 100 - (b.up / b.total) * 100 - (b.down / b.total) * 100)
})
const breadthDownW = computed(() => {
  const b = dashboard.value?.breadth
  if (!b || !b.total) return 0
  return (b.down / b.total) * 100
})

// ── 市场温度与结构：分位 / 宽度曲线 / 风格 / 集中度 ──
const breadthSeries = computed(() => metrics.value?.breadth?.series || [])

// 分位配色：热度指标高分为热（红），低分为冷（绿），中间中性
const rankTone = (t: MarketTemperatureItem) => {
  if (t.rank == null) return 'is-muted'
  // 反向指标（跌停家数）：分位越高说明越冷，配色需翻转，避免「高跌停=红色热」的误读
  const hot = t.higher_is_hot ? t.rank : 100 - t.rank
  return hot >= 75 ? 'is-hot' : hot <= 25 ? 'is-cold' : 'is-neutral'
}

// 宽度曲线：上涨率（实线+渐变面积）与站上20日线占比（虚线）同为 0-100%，共用一根纵轴。
// SVG 用 0-100 归一坐标（preserveAspectRatio="none"）保证任意宽度都能铺满；
// 文字/圆点改为 HTML 定位，避免非等比缩放下文字被横向拉扁。
const bwChart = computed(() => {
  const pts = breadthSeries.value
  if (pts.length < 3) return null
  const n = pts.length
  const xp = (i: number) => (i / (n - 1)) * 100
  // SVG 的 y 轴向下为正，故取 100 - 值；HTML 定位用 bottom = 值
  const yp = (v: number) => 100 - Math.max(0, Math.min(100, v))

  const upLine = pts.map((p, i) => `${xp(i).toFixed(2)},${yp(p.up_pct).toFixed(2)}`).join(' ')
  const area = `0,100 ${upLine} 100,100`

  // 虚线遇缺失值断开，避免把缺口连成一条假趋势
  const maSegs: string[] = []
  let cur: string[] = []
  pts.forEach((p, i) => {
    if (p.ma20_above == null) {
      if (cur.length) { maSegs.push(cur.join(' ')); cur = [] }
    } else {
      cur.push(`${xp(i).toFixed(2)},${yp(p.ma20_above).toFixed(2)}`)
    }
  })
  if (cur.length) maSegs.push(cur.join(' '))

  const dots = pts
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => i % 6 === 0 || i === n - 1)
    .map(({ p, i }) => ({
      k: `${p.date}-${i}`,
      xp: xp(i),
      yp: Math.max(0, Math.min(100, p.up_pct)),
      ma: p.ma20_above != null,
      tip: `${p.date} · 上涨率 ${p.up_pct}%${p.ma20_above == null ? '' : ` · 站上20日线 ${p.ma20_above}%`}`,
    }))

  const xTicks = [0, Math.floor(n / 2), n - 1].map((i, idx) => ({
    k: `x-${i}`,
    xp: xp(i),
    text: String(pts[i].date || '').slice(5),
    align: idx === 0 ? 'translateX(0)' : idx === 2 ? 'translateX(-100%)' : 'translateX(-50%)',
  }))

  // 一年中位上涨率：作为「常态水位」参照，让今天的 13.9% 一眼看出偏离多少
  const sorted = pts.map(p => p.up_pct).sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]

  return {
    upLine,
    area,
    maSegs,
    dots,
    xTicks,
    yTicks: [0, 25, 50, 75, 100].map(v => ({ v })),
    today: { ...pts[n - 1], median: Math.round(median * 10) / 10 },
  }
})

// 市值风格结论：先说「钱偏大还是偏小」，再看三根条验证
const styleVerdict = computed(() => {
  const s = metrics.value?.style
  if (!s?.buckets?.length) return null
  const spread = s.spread
  const allDown = s.buckets.every(b => b.pct < 0)
  const allUp = s.buckets.every(b => b.pct > 0)
  const big = spread >= 0
  const label = big ? '资金相对偏大盘' : '资金相对偏小盘'
  let detail = big
    ? '大盘组表现最好，权重更抗跌、更受资金照顾'
    : '小盘组表现最好，题材更活跃、弹性更大'
  if (allDown) {
    detail = big
      ? `三组都在跌，但越小盘跌得越多（差 ${Math.abs(spread).toFixed(2)} 个百分点），抛压集中在小盘`
      : `三组都在跌，但越小盘跌得越少（差 ${Math.abs(spread).toFixed(2)} 个百分点），小盘相对抗跌`
  } else if (allUp) {
    detail = big
      ? `三组都在涨，大盘涨得更多（多 ${Math.abs(spread).toFixed(2)} 个百分点），资金抱团权重`
      : `三组都在涨，小盘涨得更多（多 ${Math.abs(spread).toFixed(2)} 个百分点），资金更愿意做题材`
  }
  return { label, detail, tone: big ? 'defense' : 'offense' }
})

const concTopW = computed(() => Math.min(100, Math.max(0, metrics.value?.concentration?.top10_share || 0)))

const styleMax = computed(() =>
  Math.max(1, ...(metrics.value?.style?.buckets || []).map(b => Math.abs(b.pct)))
)
// 风格条以中线为 0 轴，条长按组内最大绝对涨跌幅归一（涨向右 / 跌向左）
const styleBar = (pct: number) => {
  const w = Math.max(4, Math.round((Math.abs(pct) / styleMax.value) * 50))
  return pct >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }
}

// 带超时的请求包装
const withTimeout = <T>(promise: Promise<T>, timeoutMs: number = 15000): Promise<T> => {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      setTimeout(() => {
        reject(new Error(`请求超时 (${timeoutMs}ms)`))
      }, timeoutMs)
    })
  ])
}

const loadAshare = async (refresh = false) => {
  loading.value = true
  // 开盘情景独立加载：不阻塞指数/看板，失败也不计入页头告警
  loadPreOpen(refresh)
  try {
    // 03 盘中事实：事件（04）与研判（01/05）不在这里刷新，避免 60s 轮询连带外部数据源
    const results = await Promise.allSettled([
      withTimeout(vibeApi.getIndices(), 15000),
      withTimeout(vibeApi.getDashboard(refresh), 60000),
      withTimeout(vibeApi.getMarketMetrics(refresh), 20000),
    ])

    // 逐个处理结果，失败不影响其他数据显示
    const [idxRes, dashRes, metRes] = results
    if (idxRes.status === 'fulfilled') {
      indices.value = (idxRes.value as any).data || []
    }
    if (dashRes.status === 'fulfilled') {
      dashboard.value = (dashRes.value as any).data || null
    }
    if (metRes.status === 'fulfilled') {
      metrics.value = (metRes.value as any).data || null
    }

    // 统计失败数量，给出提示
    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length > 0) {
      const msg = failed.map(r => (r as PromiseRejectedResult).reason.message).join(', ')
      ElMessage.warning(`${failed.length} 个接口加载超时，显示已有数据：${msg}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  vibeApi.getLatestTradeDate().then((d) => { if (d) tradeDate.value = d })
  loadAshare()
  loadPosition()
  loadSynthesis(false)
  loadEvents()
  startAutoRefresh()
})

// 页头刷新：数据类接口绕过前端缓存；AI 研判不在刷新链路，避免每次刷新都消耗 LLM
const refreshAll = () =>
  Promise.all([loadAshare(true), loadPosition(true), loadEvents()])

// 盘中每 60 秒静默刷新一次：只刷数据，不触发 AI 研判；页面隐藏时暂停
let autoTimer: number | undefined
function startAutoRefresh() {
  stopAutoRefresh()
  autoTimer = window.setInterval(() => {
    if (document.hidden) return
    if (marketState.value.cls !== 'is-open') return
    loadAshare(true)
  }, 60000)
}
function stopAutoRefresh() {
  if (autoTimer) {
    window.clearInterval(autoTimer)
    autoTimer = undefined
  }
}
onUnmounted(() => {
  stopAutoRefresh()
  if (positionRetryTimer) {
    window.clearTimeout(positionRetryTimer)
    positionRetryTimer = undefined
  }
})

// keep-alive 恢复时刷新一次（研判走缓存秒开，不重跑 LLM）
let pageInited = false
onActivated(() => {
  if (pageInited) {
    loadAshare(true)
    loadPosition()
    loadSynthesis(false)
    loadEvents()
  }
  pageInited = true
  startAutoRefresh()
})
</script>

<style scoped>
.vibe-market {
  padding: 4px;
}

/* 五层决策链的分节头：编号 + 标题 + 一句话说明 + 右侧数据时点/操作 */
.mr-sec {
  margin-bottom: 24px;
}
.mr-sec-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.mr-sec-no {
  font-family: var(--app-font-mono);
  font-size: 12px;
  font-weight: 700;
  color: var(--el-color-primary);
  letter-spacing: .5px;
}
.mr-sec-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.mr-sec-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.mr-sec-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* 01 结论区的背离预警徽标：点击直达 02 */
.mr-div-badge {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--el-color-warning);
  background: rgba(230, 162, 60, .12);
  cursor: pointer;
}

/* 通用等宽数字（分位 / 收益 / 样本量） */
.mono {
  font-family: var(--app-font-mono);
  font-variant-numeric: tabular-nums;
}

.block {
  margin-bottom: 24px;
}

/* 区块级数据时间：标注该块数据自身的生成时刻，避免与页头「更新于」混淆 */
.data-time {
  font-size: 11.5px;
  font-style: normal;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
  margin-left: 8px;
}

/* 数据时点标签：只标注「非今日实时」的部分（历史基线/历史收盘） */
.fresh-tag {
  flex: 0 0 auto;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 10.5px;
  line-height: 17px;
  white-space: nowrap;
}

.fresh-tag.is-hist {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
}

/* 页头：星期、盘中/休市、数据时点。三者组合用于回答「这份数据是不是今天的」 */
.title-weekday {
  font-style: normal;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}
.market-state {
  padding: 1px 7px;
  border-radius: 9px;
  font-size: 11.5px;
  line-height: 18px;
  border: 1px solid transparent;
}
.market-state.is-open {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-7);
}
.market-state.is-closed {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-lighter);
}
.hero-link {
  font-size: 12.5px;
  color: var(--el-color-primary);
  text-decoration: none;
  margin-right: 4px;
}
.hero-link:hover {
  text-decoration: underline;
}

/* ── 一句话结论：先给判断 ── */
.verdict {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin-bottom: 18px;
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-left: 3px solid var(--el-color-primary);
}

.verdict-tag {
  flex: 0 0 auto;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12.5px;
  font-weight: 600;
}

.verdict-text {
  flex: 1 1 320px;
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-primary);
}

.verdict-meta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}

.verdict-meta em {
  font-style: normal;
  padding: 1px 7px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.verdict-meta em.is-live {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

@media (max-width: 768px) {
  .verdict-text { flex-basis: 100%; order: 3; }
  .verdict-meta { margin-left: auto; }
}

/* 每张图一句话：这图在说什么、怎么用 */
.cap {
  margin: 10px 0 0;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

/* ── 市场温度与结构 ── */
.alert-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.alert-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  border: 1px solid transparent;
}

.alert-chip b {
  font-weight: 600;
}

.alert-chip.is-danger {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-7);
}

.alert-chip.is-warning {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  border-color: var(--el-color-warning-light-7);
}

.alert-chip.is-info {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}

.alert-chip.is-ok {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
}

.alert-row--calm {
  margin-bottom: 10px;
}

/* 温度分位卡：一条分位条 + 中位刻度（50%） */
.temp-headline {
  margin: 2px 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.temp-headline .dist-note {
  display: inline;
  margin: 0 0 0 10px;
  font-weight: 400;
}

.temp-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}

.temp-item {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
}

.temp-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.temp-label {
  font-size: 12.5px;
  color: var(--el-text-color-regular);
}

.temp-value {
  font-family: var(--app-font-mono);
  font-size: 18px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.temp-value em {
  font-style: normal;
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 2px;
}

.temp-track {
  position: relative;
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color-lighter);
  margin: 10px 0 6px;
}

.temp-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.temp-fill.is-hot { background: var(--app-up); }
.temp-fill.is-cold { background: var(--app-down); }
.temp-fill.is-neutral { background: var(--el-color-primary); }
.temp-fill.is-muted { background: var(--el-border-color); }

.temp-median {
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: 1px;
  background: var(--el-text-color-placeholder);
  opacity: 0.7;
}

.temp-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

.temp-foot b.is-hot { color: var(--app-up); }
.temp-foot b.is-cold { color: var(--app-down); }
.temp-foot b.is-neutral { color: var(--el-color-primary); }
.temp-foot b.is-muted { color: var(--el-text-color-placeholder); }

.temp-med {
  color: var(--el-text-color-placeholder);
}

/* 反向指标标注（跌停家数：分位越高越冷） */
.temp-rev {
  font-style: normal;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 10px;
  color: var(--el-text-color-placeholder);
  background: var(--el-fill-color-light);
}

.temp-pending {
  color: var(--el-text-color-placeholder);
}

/* 宽度曲线（整行） */
.width-card {
  margin-bottom: 12px;
}

/* 宽度趋势图：SVG 只画线面，刻度/圆点/标签用 HTML 定位，任意宽度都不变形 */
.bw-readout {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-left: auto;
}

.ro {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 400;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.ro b {
  font-family: var(--app-font-mono);
  font-weight: 600;
}

.ro--up b { color: var(--el-color-primary); }
.ro--ma b { color: var(--el-color-warning); }
.ro--med { color: var(--el-text-color-placeholder); }

.bw-plot {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}

.bw-yaxis {
  position: relative;
  flex: 0 0 32px;
  height: 176px;
}

.bw-yaxis span {
  position: absolute;
  right: 0;
  transform: translateY(50%);
  font-size: 9.5px;
  line-height: 1;
  color: var(--el-text-color-placeholder);
}

.bw-canvas {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 176px;
  margin-bottom: 16px;
}

.bw-gline {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--el-border-color-lighter);
}

.bw-gline.is-mid {
  background: var(--el-border-color);
  background-image: linear-gradient(90deg, var(--el-border-color) 50%, transparent 50%);
  background-size: 8px 1px;
}

.bw-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

.bw-up {
  stroke: var(--el-color-primary);
  stroke-width: 2;
  stroke-linejoin: round;
  fill: none;
}

.bw-ma {
  stroke: var(--el-color-warning);
  stroke-width: 1.6;
  stroke-dasharray: 5 3;
  fill: none;
  opacity: 0.95;
}

/* 今日竖线，标出曲线末端 */
.bw-today {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  width: 0;
  border-left: 1px dashed var(--el-color-primary-light-5);
}

.bw-pt {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  transform: translate(-50%, 50%);
  box-shadow: 0 0 0 1.5px var(--el-bg-color);
  z-index: 2;
}

.bw-tip {
  position: absolute;
  left: 50%;
  bottom: 11px;
  transform: translateX(-50%);
  padding: 3px 7px;
  border-radius: 5px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--el-box-shadow-light);
  font-size: 11px;
  line-height: 1.4;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.12s;
  z-index: 4;
}

.bw-pt:hover .bw-tip {
  opacity: 1;
}

.bw-xaxis {
  position: absolute;
  bottom: -16px;
  font-size: 10px;
  line-height: 1;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
}

.bw-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.bw-key {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.bw-key i {
  display: inline-block;
  width: 14px;
  height: 2px;
  border-radius: 1px;
  background: var(--el-color-primary);
}

.bw-key i.k-ma {
  height: 0;
  border-top: 1.5px dashed var(--el-color-warning);
  background: none;
}

.bw-key i.k-mid {
  height: 0;
  border-top: 1px dashed var(--el-border-color);
  background: none;
  width: 10px;
}

/* 结构快照 */
.snap-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.snap-row--tight {
  grid-template-columns: repeat(2, 1fr);
  margin-top: 12px;
}

.snap-item {
  min-width: 0;
}

.snap-label {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

.snap-value {
  font-family: var(--app-font-mono);
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.4;
}

/* 风格轮动 + 成交额集中度 */
.mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: stretch;
}

.style-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 4px 0 10px;
}

.style-row {
  display: grid;
  grid-template-columns: 34px 48px 1fr 66px;
  align-items: center;
  gap: 8px;
}

.style-name {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.style-count {
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}

/* 市值风格结论条：先给「钱偏哪边」，条形图只作佐证 */
.style-verdict {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin: 2px 0 12px;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}

.style-verdict b {
  font-size: 12.5px;
  white-space: nowrap;
}

.style-verdict span {
  color: var(--el-text-color-regular);
}

.style-verdict.tone-defense {
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-info);
}

.style-verdict.tone-offense {
  background: var(--el-color-danger-light-9);
  border-left: 3px solid var(--el-color-danger);
}

.style-track {
  position: relative;
  height: 10px;
  border-radius: 3px;
  background: var(--el-fill-color-lighter);
}

.style-axis {
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: 1px;
  background: var(--el-border-color);
}

.style-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 3px;
}

.style-fill.is-up {
  background: linear-gradient(90deg, #f8a5a0 0%, #f56c6c 100%);
  border-radius: 0 3px 3px 0;
}

.style-fill.is-down {
  background: linear-gradient(90deg, #67c23a 0%, #95d475 100%);
  border-radius: 3px 0 0 3px;
}

.style-val {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  text-align: right;
}

/* 集中度条 */
.conc-bar {
  display: flex;
  height: 10px;
  border-radius: 3px;
  overflow: hidden;
  margin: 6px 0 6px;
  background: var(--el-fill-color-lighter);
}

.conc-seg {
  height: 100%;
}

.conc-top {
  background: var(--el-color-primary);
  opacity: 0.85;
}

.conc-rest {
  flex: 1;
  background: var(--el-fill-color-dark);
}

.conc-legend {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

.conc-legend .lg-up { color: var(--el-color-primary); }
.conc-legend .lg-rest { color: var(--el-text-color-placeholder); }

.rank-empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  padding: 8px 0;
}

/* ── 开盘情景：结论先行，刻度+明细两层，弱化装饰只保留方向色 ── */
.preopen-block {
  margin-bottom: 20px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-blank);
}

.preopen-block--loading {
  display: flex;
  align-items: center;
  gap: 10px;
}

.preopen-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.preopen-kicker {
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--el-text-color-placeholder);
}

.preopen-verdict {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.preopen-verdict em {
  font-style: normal;
  font-family: var(--app-font-mono);
  font-size: 15px;
  font-weight: 600;
  margin-left: 6px;
}

.preopen-basis {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.preopen-tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10.5px;
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}

.preopen-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.preopen-actions .data-time { margin-left: 0; }

.preopen-toggle {
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  user-select: none;
}

.preopen-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}

.tone-up { color: var(--app-up); }
.tone-down { color: var(--app-down); }
.tone-flat { color: var(--el-text-color-primary); }

/* 五档刻度：区间宽度与幅度成比例（-1.5% ~ +1.5%，每 0.1% = 1 份） */
.scenario-scale {
  position: relative;
  padding-top: 10px;
}

.scenario-track {
  display: grid;
  grid-template-columns: 5fr 7fr 6fr 7fr 5fr;
  gap: 2px;
}

.scenario-seg {
  padding: 7px 4px 6px;
  text-align: center;
  border: 1px solid transparent;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.scenario-seg .seg-label {
  display: block;
  font-size: 12px;
  line-height: 1.3;
}

.scenario-seg .seg-range {
  display: block;
  margin-top: 2px;
  font-family: var(--app-font-mono);
  font-size: 10px;
  opacity: 0.65;
  white-space: nowrap;
}

.scenario-seg.active {
  font-weight: 600;
}

.scenario-seg.active.tone-up {
  background: rgba(245, 108, 108, 0.1);
  border-color: var(--app-up);
  color: var(--app-up);
}

.scenario-seg.active.tone-down {
  background: rgba(103, 194, 58, 0.1);
  border-color: var(--app-down);
  color: var(--app-down);
}

.scenario-seg.active.tone-flat {
  background: var(--el-fill-color);
  border-color: var(--el-border-color);
  color: var(--el-text-color-primary);
}

.scenario-ptr {
  position: absolute;
  top: 0;
  width: 0;
  height: 0;
  transform: translateX(-50%);
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 7px solid currentColor;
}

.preopen-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.meta-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.meta-label {
  flex: 0 0 58px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.meta-items {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 20px;
}

.meta-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
}

.meta-item b {
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.meta-item i {
  font-style: normal;
  font-family: var(--app-font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.meta-item em {
  font-style: normal;
  font-size: 11px;
}

.meta-item--key b {
  color: var(--el-text-color-regular);
}

.meta-item--key i {
  font-size: 15px;
}

.meta-date {
  margin-left: auto;
  font-family: var(--app-font-mono);
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}

.meta-item em.up,
.meta-item i.up { color: var(--app-up); }
.meta-item em.down,
.meta-item i.down { color: var(--app-down); }
.meta-item em.flat { color: var(--el-text-color-placeholder); }

.preopen-note {
  font-size: 11px;
  line-height: 1.5;
  color: var(--el-text-color-placeholder);
}

@media (max-width: 900px) {
  .preopen-verdict { font-size: 18px; }
  .scenario-seg .seg-label { font-size: 11px; }
  .scenario-seg .seg-range { display: none; }
  .meta-label { flex-basis: 100%; }
  .meta-row { flex-direction: column; gap: 4px; }
  .meta-date { margin-left: 0; }
}

.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.block-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.block-title .el-icon {
  color: var(--el-color-primary);
}

.block-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.block-more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}

.block-more:hover {
  opacity: 0.8;
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.idx-card {
  border-radius: 8px;
}

.idx-card :deep(.el-card__body) {
  padding: 16px;
}

.idx-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: flex;
  align-items: center;
  gap: 6px;
}

.idx-name .region {
  margin-left: 4px;
  padding: 0 6px;
  font-size: 11px;
  line-height: 16px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  border-radius: 4px;
  vertical-align: 1px;
}

.idx-price {
  font-family: var(--app-font-mono);
  font-size: 26px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 8px 0 4px;
  letter-spacing: -0.5px;
}

.idx-change {
  font-family: var(--app-font-mono);
  font-size: 14px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.idx-change .amt {
  font-size: 12px;
  opacity: 0.8;
}

.empty-card :deep(.el-empty) {
  padding: 12px 0;
  margin: 0;
}

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 768px) {
  .grid-4 { grid-template-columns: repeat(2, 1fr); }
}

/* ===== 市场看板（借鉴 tickflow Dashboard）===== */
.kpi-sep {
  color: var(--el-text-color-placeholder);
  margin: 0 3px;
  font-weight: 400;
}

.dash-main {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.dash-card {
  border-radius: 8px;
}

.dash-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
}

/* 标题行内并排放尾部读数（宽度趋势卡片用） */
.card-title--flex {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
}

/* 雷达图 */
.radar-wrap {
  display: flex;
  justify-content: center;
  padding: 4px 0;
}

.radar-svg {
  width: 260px;
  height: 260px;
}

.radar-score {
  font-family: var(--app-font-mono);
  font-size: 26px;
  font-weight: 700;
  fill: var(--el-text-color-primary);
}

.radar-label {
  font-size: 11px;
  fill: var(--el-text-color-regular);
}

.radar-empty {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}

/* 涨跌分布 */
.dist-bars {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 152px;
  padding: 0 2px;
}

.dist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}

.dist-count {
  font-size: 10px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.dist-bar {
  width: 100%;
  max-width: 24px;
  border-radius: 3px 3px 0 0;
  min-height: 4px;
}

.dist-up { background: var(--app-up); }
.dist-flat { background: var(--app-flat); }
.dist-down { background: var(--app-down); }

/* 分布图口径说明（标题旁小字，常显） */
.dist-note {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}

.dist-label {
  font-size: 9px;
  line-height: 1.15;
  text-align: center;
  word-break: break-word;
  color: var(--el-text-color-placeholder);
  margin-top: 5px;
  white-space: normal;
}

.breadth-bar {
  margin-top: 14px;
}

.breadth-track {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--el-fill-color-light);
}

.breadth-up { background: var(--app-up); }
.breadth-flat { background: var(--app-flat); }
.breadth-down { background: var(--app-down); }

.breadth-legend {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 12px;
}

.lg-up { color: var(--app-up); }
.lg-flat { color: var(--app-flat); }
.lg-down { color: var(--app-down); }

/* 分布图脚注：强弱股与平均涨跌（替代原 KPI 行） */
.dist-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.dist-foot b {
  font-family: var(--app-font-mono);
  font-weight: 600;
}

.dist-foot b.up { color: var(--app-up); }
.dist-foot b.down { color: var(--app-down); }

@media (max-width: 1200px) {
  .temp-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 900px) {
  .mini-grid { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .dash-main { grid-template-columns: 1fr; }
  .temp-grid { grid-template-columns: repeat(2, 1fr); }
  .bw-canvas { height: 140px; }
  .bw-yaxis { height: 140px; }
  .snap-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
}

/* ══════════════════════════════════════════════════════════════════════
   01 今日结论 / 05 推理过程（原综合研判页搬入，保持同一视觉语言）
   ══════════════════════════════════════════════════════════════════════ */

.syn-loading {
  padding: 8px 0;
}
.syn-loading-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* 信心度「含事件」角标 + 悬浮明细 */
.conf-badge {
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 6px;
  font-style: normal;
  font-size: 9px;
  background: rgba(43, 108, 176, .14);
  color: #2b6cb0;
}
.conf-pop-title {
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.conf-pop-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--el-text-color-regular);
}
.conf-pop-row em { font-style: normal; font-weight: 600; white-space: nowrap; }
.dir-bull { color: var(--app-up); }
.dir-bear { color: var(--app-down); }
.dir-neutral { color: var(--el-text-color-secondary); }

/* ── 04 事件四行卡 ── */
.ev-list { display: flex; flex-direction: column; gap: 8px; }
.ev-card {
  border-left: 3px solid var(--el-border-color);
  box-shadow: none;
}
.ev-card.impact-volatility {
  border-left-color: var(--el-color-warning);
  background: rgba(230, 162, 60, .04);
}
.ev-card.impact-direction {
  border-left-color: var(--el-color-primary);
  background: rgba(43, 108, 176, .04);
}
.ev-card.is-expired { opacity: .72; }
.ev-card :deep(.el-card__body) { padding: 10px 12px; }

.ev-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 13px;
}
.ev-row + .ev-row { margin-top: 6px; }
.ev-main { font-weight: 600; }
.ev-time {
  flex: none;
  font-family: var(--app-font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.ev-title {
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ev-surprise {
  flex: none;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--el-fill-color);
}
.ev-surprise.sur-bull { color: var(--app-up); background: rgba(245, 108, 108, .12); }
.ev-surprise.sur-bear { color: var(--app-down); background: rgba(103, 194, 58, .12); }
.ev-surprise.sur-neutral { color: var(--el-text-color-secondary); }
.ev-status {
  flex: none;
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.ev-status.status-pending { color: var(--el-color-warning); }
.ev-toggle {
  flex: none;
  font-size: 11.5px;
  color: var(--el-color-primary);
  cursor: pointer;
}
.ev-label {
  flex: none;
  width: 34px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}
.ev-impact-val { font-weight: 600; }
.ev-action {
  align-items: flex-start;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.ev-sectors { flex-wrap: wrap; }
.ev-tag {
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 11px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}
.ev-detail {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.ev-trans {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.ev-trans-step em {
  font-style: normal;
  margin-left: 4px;
  color: var(--el-text-color-placeholder);
}
.ev-watch { font-size: 12px; line-height: 1.6; color: #2b6cb0; }
.ev-empty {
  padding: 14px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--el-text-color-placeholder);
}

/* ── 01 结论横幅 ── */
.syn-hero {
  position: relative;
  overflow: hidden;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow);
  padding: 20px 22px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.syn-hero--bull { border-top: 3px solid var(--app-up); }
.syn-hero--bear { border-top: 3px solid var(--app-down); }
.syn-hero--neutral { border-top: 3px solid var(--el-color-primary); }

.syn-hero-top {
  display: flex;
  align-items: center;
  gap: 20px;
  position: relative;
}
.syn-direc-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 92px;
}
.syn-direc-zh { font-size: 12px; color: var(--el-text-color-placeholder); }
.syn-direc-main {
  font-size: 32px;
  font-weight: 800;
  letter-spacing: 3px;
  line-height: 1.05;
}
.syn-hero--bull .syn-direc-main { color: var(--app-up); }
.syn-hero--bear .syn-direc-main { color: var(--app-down); }
.syn-hero--neutral .syn-direc-main { color: var(--el-color-primary); }

.syn-conf-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 0 18px;
  border-right: 1px dashed var(--el-border-color-lighter);
  border-left: 1px dashed var(--el-border-color-lighter);
}
.syn-conf-ring {
  --pct: 0%;
  --ring-color: #2b6cb0;
  width: 60px; height: 60px;
  border-radius: 50%;
  background: conic-gradient(var(--ring-color) var(--pct), var(--el-fill-color-extra-light) 0);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
}
.syn-conf-ring::before {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: 50%;
  background: #fff;
}
.syn-conf-num {
  position: relative;
  z-index: 1;
  font-family: var(--app-font-mono);
  font-size: 17px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1;
}
.syn-conf-unit {
  position: relative;
  z-index: 1;
  font-size: 9px;
  color: var(--el-text-color-placeholder);
  margin-top: 1px;
}
.syn-conf-label { font-size: 11px; color: var(--el-text-color-placeholder); }

.syn-tags {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.syn-hero-concl .syn-concl-text {
  font-size: 15px;
  line-height: 1.85;
  color: var(--el-text-color-primary);
}

/* 首屏决策卡：主攻 / 回避 / 仓位 */
.syn-decision {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.syn-dec-card {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-left-width: 3px;
}
.syn-dec-card--main {
  border-left-color: var(--app-up);
  background: rgba(245, 108, 108, .05);
}
.syn-dec-card--avoid {
  border-left-color: var(--app-down);
  background: rgba(103, 194, 58, .05);
}
.syn-dec-card--pos {
  border-left-color: var(--el-color-warning);
  background: rgba(230, 162, 60, .06);
}
.syn-dec-label {
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: .5px;
  margin-bottom: 4px;
}
.syn-dec-card--main .syn-dec-label { color: var(--app-up); }
.syn-dec-card--avoid .syn-dec-label { color: var(--app-down); }
.syn-dec-card--pos .syn-dec-label { color: var(--el-color-warning); }
.syn-dec-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

/* ── 05 推理过程 ── */
.syn-panel {
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
}
.syn-panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 8px;
}
.syn-panel-title.watch { color: var(--el-color-primary); }
.syn-panel-title.strat { color: var(--el-color-warning); }
.syn-panel-title.status { color: #2b6cb0; }
.syn-panel-title.reasons { color: var(--el-color-info); }
.syn-panel-title.extra { color: #805ad5; }
.syn-panel-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.syn-panel-list li {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.syn-plain-text,
.syn-strat-text {
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--el-text-color-regular);
}

.syn-reason {
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: none;
}
.syn-reason :deep(.el-collapse-item__header) {
  height: auto;
  padding: 8px 2px;
  border-bottom: none;
  gap: 10px;
  line-height: 1.5;
}
.syn-reason :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}
.syn-reason-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.syn-reason-sub {
  margin-left: auto;
  padding-right: 8px;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.syn-reason-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 0 4px;
}

/* 今日观察 · 外围传导 */
.syn-ext {
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(43, 108, 176, .06);
  border: 1px solid rgba(43, 108, 176, .18);
}
.syn-ext-label {
  font-size: 12px;
  font-weight: 700;
  color: #2b6cb0;
  margin-bottom: 4px;
}
.syn-ext-text {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

/* 风险提示 */
.syn-risk {
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(230, 162, 60, .08);
  border: 1px solid rgba(230, 162, 60, .22);
}
.syn-risk-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #b7791f;
  margin-bottom: 4px;
}
.syn-risk-list { margin: 0; padding-left: 18px; }
.syn-risk-list li {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

/* ── 今日买卖清单 ── */
.syn-guide {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow);
}
.syn-guide-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.syn-guide-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.syn-guide-hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.syn-guide-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.syn-guide-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.syn-guide-col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 700;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.syn-guide-col-head .buy { color: var(--app-up); }
.syn-guide-col-head .sell { color: var(--app-down); }
.syn-guide-count {
  font-weight: 500;
  color: var(--el-text-color-placeholder);
}
.syn-guide-item {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.syn-guide-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.syn-guide-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.syn-guide-name:hover { color: var(--el-color-primary); }
.syn-guide-code {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}
.syn-guide-row :deep(.el-tag) { margin-left: auto; flex: none; }
.syn-guide-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.syn-guide-metrics .is-near { color: var(--el-color-warning); }
.syn-guide-metrics .up { color: var(--app-up); }
.syn-guide-metrics .down { color: var(--app-down); }
.syn-guide-metrics .mono {
  font-family: var(--app-font-mono);
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.syn-guide-metrics .up .mono { color: var(--app-up); }
.syn-guide-metrics .down .mono { color: var(--app-down); }
.syn-guide-advice {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.syn-guide-empty {
  padding: 14px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--el-text-color-placeholder);
}

/* ══════════════════════════════════════════════════════════════════════
   02 当前位置：0–100 位置标尺 / 逃顶·判底触发条 / 历史曲线 / 指标横条
   ══════════════════════════════════════════════════════════════════════ */

.pos-pending {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-radius: var(--app-radius-lg);
  border: 1px dashed var(--el-border-color);
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
}

/* 顶部：判定 + 大分数 + 位置标尺 */
.pos-hero {
  padding: 14px 16px 12px;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow);
}
.pos-hero-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.pos-hero-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}
.pos-zone-badge {
  flex: none;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.pos-hero.zone-overheated .pos-zone-badge { color: #fff; background: var(--app-up); }
.pos-hero.zone-warm .pos-zone-badge { color: #b26a00; background: rgba(230, 162, 60, .16); }
.pos-hero.zone-neutral .pos-zone-badge { color: var(--el-color-primary); background: rgba(43, 108, 176, .12); }
.pos-hero.zone-cool .pos-zone-badge { color: #3f8a2e; background: rgba(103, 194, 58, .14); }
.pos-hero.zone-oversold .pos-zone-badge { color: #fff; background: var(--app-down); }
.pos-verdict-title {
  font-size: 18px;
  font-weight: 800;
  line-height: 1.3;
  color: var(--el-text-color-primary);
}
.pos-verdict-sub {
  margin-top: 3px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--el-text-color-secondary);
}
.pos-hero-score {
  flex: none;
  text-align: right;
}
.pos-score-num {
  font-family: var(--app-font-mono);
  font-size: 34px;
  font-weight: 800;
  line-height: 1;
  color: var(--el-text-color-primary);
}
.pos-score-num em {
  margin-left: 1px;
  font-style: normal;
  font-size: 15px;
  color: var(--el-text-color-placeholder);
}
.pos-score-cap {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}

/* 位置标尺：五档分区 + 指针 + 各指标热度刻点 */
.pos-gauge {
  position: relative;
  margin-top: 22px;
  padding: 0 2px;
}
.pos-gauge-bar {
  position: relative;
  display: flex;
  height: 22px;
  border-radius: 6px;
}
.pos-gauge-band {
  display: flex;
  align-items: center;
  justify-content: center;
  font-style: normal;
  font-size: 10.5px;
  letter-spacing: .5px;
  color: #fff;
  opacity: .95;
}
.pos-gauge-band.oversold { background: linear-gradient(180deg, #5cb87a, #49a568); border-radius: 6px 0 0 6px; }
.pos-gauge-band.cool { background: linear-gradient(180deg, #b9d8ac, #94c183); color: #2f5539; }
.pos-gauge-band.neutral { background: #e3e7ee; color: #4b5563; }
.pos-gauge-band.warm { background: linear-gradient(180deg, #f2b981, #e79a5c); }
.pos-gauge-band.overheated { background: linear-gradient(180deg, #e8736c, #d6453d); border-radius: 0 6px 6px 0; }
.pos-gauge-needle {
  position: absolute;
  top: -7px;
  bottom: -7px;
  width: 3px;
  margin-left: -1.5px;
  border-radius: 2px;
  background: var(--el-text-color-primary);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, .85);
}
.pos-gauge-bubble {
  position: absolute;
  top: -23px;
  transform: translateX(-50%);
  padding: 1px 6px;
  border-radius: 6px;
  font-style: normal;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--app-font-mono);
  color: #fff;
  background: var(--el-text-color-primary);
  white-space: nowrap;
}
.pos-gauge-scale {
  position: relative;
  height: 16px;
  margin-top: 3px;
}
.pos-gauge-scale span {
  position: absolute;
  transform: translateX(-50%);
  font-family: var(--app-font-mono);
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}
.pos-gauge-dots {
  position: relative;
  height: 24px;
  margin-top: 1px;
}
.pos-gauge-dot {
  position: absolute;
  top: 2px;
  width: 8px;
  height: 8px;
  margin-left: -4px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px var(--el-fill-color-blank);
}
.pos-gauge-dot.is-low { top: 14px; }
.pos-gauge-dot.is-hot { background: var(--app-up); }
.pos-gauge-dot.is-cold { background: var(--app-down); }
.pos-gauge-dot.is-neutral { background: var(--el-color-primary); }
.pos-gauge-dot.is-muted { background: var(--el-border-color); }

.pos-distance {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.pos-distance-chip {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}
.pos-distance-chip.is-hot { color: var(--app-up); border-color: rgba(245, 108, 108, .35); background: rgba(245, 108, 108, .08); }
.pos-distance-chip.is-cold { color: var(--app-down); border-color: rgba(103, 194, 58, .35); background: rgba(103, 194, 58, .08); }
.pos-distance-chip.is-neutral { color: var(--el-text-color-regular); }
.pos-distance-chip.is-meta { color: var(--el-text-color-placeholder); background: transparent; }
.pos-advice {
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

/* 逃顶 / 判断底部：触发阈值条 + 历史证据 */
.pos-guide {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}
.pos-guide-card {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-top: 3px solid var(--el-border-color);
  background: var(--el-fill-color-blank);
}
.pos-guide-card.is-top { border-top-color: var(--app-up); }
.pos-guide-card.is-bottom { border-top-color: var(--app-down); }
.pos-guide-card.is-active { background: var(--el-fill-color-light); }
.pos-guide-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.pos-guide-title { font-size: 13px; font-weight: 700; color: var(--el-text-color-primary); }
.pos-guide-flag {
  flex: none;
  padding: 0 6px;
  border-radius: 8px;
  font-style: normal;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  background: var(--el-fill-color-light);
}
.pos-guide-flag.is-on { color: var(--el-color-warning); background: rgba(230, 162, 60, .14); }
.pos-guide-track {
  position: relative;
  height: 6px;
  margin-top: 10px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
}
.pos-guide-zone {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 3px;
}
.pos-guide-zone.is-top { left: 80%; right: 0; background: linear-gradient(90deg, rgba(232, 115, 108, .35), var(--app-up)); }
.pos-guide-zone.is-bottom { left: 0; width: 20%; background: linear-gradient(90deg, var(--app-down), rgba(92, 184, 122, .35)); }
.pos-guide-cursor {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 2px;
  margin-left: -1px;
  border-radius: 2px;
  background: var(--el-text-color-primary);
}
.pos-guide-cursor b {
  position: absolute;
  top: -15px;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--app-font-mono);
  font-size: 10px;
  color: var(--el-text-color-primary);
}
.pos-guide-rule { margin-top: 14px; font-size: 12px; color: var(--el-text-color-secondary); }
.pos-guide-stats { margin-top: 4px; font-size: 12px; color: var(--el-text-color-regular); }
.pos-guide-advice { margin-top: 4px; font-size: 12px; color: var(--el-text-color-placeholder); }

/* 指标分组：估值 / 位置 / 情绪 / 参与度 / 底部特征 */
.pos-group { margin-top: 12px; }
.pos-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.pos-group-hint {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}
.pos-group .pos-bullets { margin-top: 6px; }

/* 合成分位说明 + 内部结构 chips + 分化提示 */
.pos-explain {
  margin-top: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px dashed var(--el-border-color);
  background: var(--el-fill-color-lighter);
}
.pos-explain-text {
  display: flex;
  gap: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.pos-explain-text .el-icon {
  flex: none;
  margin-top: 2px;
  color: var(--el-color-primary);
}
.pos-comp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.pos-comp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}
.pos-comp-chip i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.pos-comp-chip em { font-style: normal; color: var(--el-text-color-secondary); }
.pos-comp-chip b { font-family: var(--app-font-mono); font-size: 11.5px; }
.pos-comp-chip.is-hot i { background: var(--app-up); }
.pos-comp-chip.is-hot b { color: var(--app-up); }
.pos-comp-chip.is-cold i { background: var(--app-down); }
.pos-comp-chip.is-cold b { color: var(--app-down); }
.pos-comp-chip.is-neutral i { background: var(--el-color-primary); }
.pos-comp-chip.is-neutral b { color: var(--el-color-primary); }
.pos-comp-chip.is-muted i { background: var(--el-border-color); }
.pos-spread {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-color-warning);
}
.pos-spread .el-icon { flex: none; margin-top: 2px; }

/* 历史曲线 / 未来收益：统一块头 */
.pos-chart,
.pos-fwd {
  margin-top: 12px;
  padding: 12px 14px 8px;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
}
.pos-block-head {
  margin-bottom: 4px;
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.pos-block-head .dist-note {
  display: inline;
  margin-top: 0;
  margin-left: 8px;
}
.chart-200 { width: 100%; height: 200px; }

/* 历史类比（04） */
.pos-analog {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}
.pos-analog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.pos-analog-title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.pos-analog-summary {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.pos-analog-summary b { margin-left: 4px; }
.pos-analog-summary b.up { color: var(--app-up); }
.pos-analog-summary b.down { color: var(--app-down); }
.pos-analog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.pos-analog-case {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  font-size: 12px;
}
.pos-analog-date { font-weight: 700; color: var(--el-text-color-primary); }
.pos-analog-sim,
.pos-analog-comp { font-size: 11.5px; color: var(--el-text-color-placeholder); }
.pos-analog-case .up { color: var(--app-up); }
.pos-analog-case .down { color: var(--app-down); }

/* 单项指标：横条（分位越靠右越热） */
.pos-bullets {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 20px;
  margin-top: 6px;
}
.pos-bullet {
  display: grid;
  grid-template-columns: 104px minmax(0, 1fr) 66px 42px;
  align-items: center;
  gap: 8px;
  padding: 5px 6px;
  border-radius: 6px;
  font-size: 12px;
  min-width: 0;
}
.pos-bullet:hover { background: var(--el-fill-color-light); }
.pos-bullet-label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: help;
}
.pos-bullet-label .el-icon {
  flex: none;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.pos-bullet-track {
  position: relative;
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
}
.pos-bullet-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 3px;
}
.pos-bullet-fill.is-hot { background: var(--app-up); }
.pos-bullet-fill.is-cold { background: var(--app-down); }
.pos-bullet-fill.is-neutral { background: var(--el-color-primary); }
.pos-bullet-fill.is-muted { background: var(--el-border-color); }
.pos-bullet-med {
  position: absolute;
  top: -2px;
  bottom: -2px;
  left: 50%;
  width: 1px;
  background: var(--el-text-color-placeholder);
  opacity: .7;
}
.pos-bullet-value {
  text-align: right;
  font-family: var(--app-font-mono);
  font-weight: 700;
  color: var(--el-text-color-primary);
  white-space: nowrap;
}
.pos-bullet-value em {
  margin-left: 2px;
  font-style: normal;
  font-size: 10.5px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}
.pos-bullet-pct {
  text-align: right;
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.pos-bullet-pct.is-hot { color: var(--app-up); }
.pos-bullet-pct.is-cold { color: var(--app-down); }
.pos-bullet-pct.is-neutral { color: var(--el-text-color-regular); }

.pos-div-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.pos-div-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.pos-div-chip b { flex: none; font-weight: 700; }
.pos-div-chip.is-warning { border-color: rgba(230, 162, 60, .35); background: rgba(230, 162, 60, .08); }
.pos-div-chip.is-danger { border-color: rgba(245, 108, 108, .35); background: rgba(245, 108, 108, .08); }
.pos-div-chip.is-info { border-color: rgba(43, 108, 176, .3); background: rgba(43, 108, 176, .06); }

.pos-fwd-rows {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 6px;
}
.pos-fwd-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) 76px 132px;
  align-items: center;
  gap: 10px;
  padding: 5px 6px;
  border-radius: 6px;
  font-size: 12px;
}
.pos-fwd-row.is-current {
  background: rgba(43, 108, 176, .08);
  font-weight: 600;
}
.pos-fwd-label {
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.pos-fwd-label em {
  margin-left: 5px;
  padding: 0 5px;
  border-radius: 5px;
  font-style: normal;
  font-size: 10.5px;
  color: var(--el-color-primary);
  background: rgba(43, 108, 176, .12);
}
.pos-fwd-track {
  position: relative;
  height: 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}
.pos-fwd-zero {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: var(--el-border-color);
}
.pos-fwd-bar {
  position: absolute;
  top: 2px;
  bottom: 2px;
  border-radius: 3px;
  opacity: .8;
}
.pos-fwd-bar.up { background: var(--app-up); }
.pos-fwd-bar.down { background: var(--app-down); }
.pos-fwd-val {
  text-align: right;
  font-weight: 600;
  color: var(--el-text-color-regular);
  white-space: nowrap;
}
.pos-fwd-val.up { color: var(--app-up); }
.pos-fwd-val.down { color: var(--app-down); }
.pos-fwd-meta {
  text-align: right;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .pos-analog-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pos-bullets { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .syn-decision { grid-template-columns: 1fr; }
  .syn-guide-grid { grid-template-columns: 1fr; }
  .pos-guide { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .pos-analog-grid { grid-template-columns: 1fr; }
  .syn-hero { padding: 16px; }
  .syn-hero-top { flex-wrap: wrap; gap: 12px; }
  .syn-tags { margin-left: 0; }
  .syn-direc-main { font-size: 26px; }
  .syn-conf-wrap { padding: 0 12px; }
  .pos-hero { padding: 12px 12px 10px; }
  .pos-hero-head { flex-wrap: wrap; gap: 10px; }
  .pos-score-num { font-size: 26px; }
  .pos-gauge-band { font-size: 9px; letter-spacing: 0; }
  .pos-bullet { grid-template-columns: 92px minmax(0, 1fr) 58px 38px; gap: 6px; }
  .pos-fwd-row { grid-template-columns: 74px minmax(0, 1fr) 60px; gap: 8px; font-size: 11.5px; }
  .pos-fwd-meta { display: none; }
}
</style>
