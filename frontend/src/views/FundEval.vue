<template>
  <div class="fund-eval-page">
    <div class="dashboard-card">
      <h2 class="section-title">{{ currentView === 'list' ? '自选基金' : '基金评测' }}</h2>

      <!-- 列表视图 -->
      <template v-if="currentView === 'list'">
        <el-row :gutter="20" class="list-toolbar" align="middle">
          <el-col :span="9">
            <el-input
              v-model="fundCode"
              placeholder="输入基金代码 → 评测"
              size="default"
              @keyup.enter="handleEvaluate"
              clearable
            >
              <template #append>
                <el-button type="primary" @click="handleEvaluate" :disabled="!fundCode">评测</el-button>
              </template>
            </el-input>
          </el-col>
          <el-col :span="9">
            <el-input
              v-model="searchKeyword"
              placeholder="搜索当前列表（名称或代码）"
              size="default"
              clearable
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </el-col>
          <el-col :span="6" style="text-align: right">
            <el-radio-group v-model="activeTab" size="default">
              <el-radio-button label="favorites">自选</el-radio-button>
              <el-radio-button label="all">全部已测评</el-radio-button>
            </el-radio-group>
          </el-col>
        </el-row>

        <!-- 热门推荐 -->
        <div class="suggestions">
          <span>热门基金：</span>
          <el-tag
            v-for="item in suggestedFunds"
            :key="item.code"
            @click="viewDetail(item.code)"
            style="cursor: pointer; margin-right: 8px; margin-bottom: 4px"
          >
            {{ item.code }} {{ item.name }}
          </el-tag>
        </div>

        <!-- 基金列表 -->
        <div v-if="filteredFunds.length" class="favorite-list" style="margin-top: 24px">
          <el-table
            :data="filteredFunds"
            stripe
            style="width: 100%"
            @row-click="(row: any) => viewDetail(row.code)"
            @selection-change="onSelectionChange"
            ref="tableRef"
            row-key="code"
          >
            <el-table-column type="selection" width="48" :selectable="isRowSelectable" />
            <el-table-column prop="name" label="基金名称" min-width="180">
              <template #default="{ row }">
                <div style="font-weight: 500">{{ row.name }}</div>
                <div style="font-size: 12px; color: #909399">{{ row.code }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="fund_type" label="类型" width="100">
              <template #default="{ row }">
                {{ fundTypeLabel(row.fund_type) || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="manager" label="基金经理" width="120" />
            <el-table-column prop="score" label="综合评分" width="100" align="center">
              <template #default="{ row }">
                <span
                  v-if="row.score !== null && row.score !== undefined"
                  class="favorite-score"
                  :class="getScoreClass(row.score)"
                >
                  {{ row.score }}
                </span>
                <el-tag v-else size="small" type="info">未评测</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="return_1y" label="近1年收益" width="120" align="right">
              <template #default="{ row }">
                <span
                  v-if="row.return_1y !== null && row.return_1y !== undefined"
                  :class="row.return_1y >= 0 ? 'return-positive' : 'return-negative'"
                >
                  {{ `${row.return_1y >= 0 ? '+' : ''}${row.return_1y.toFixed(2)}%` }}
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" align="center">
              <template #default="{ row }">
                <el-button type="primary" size="small" @click.stop="viewDetail(row.code)">详情</el-button>
                <el-button
                  v-if="favoriteCodeSet.has(row.code)"
                  type="danger"
                  size="small"
                  plain
                  @click.stop="toggleFavorite(row.code)"
                >
                  取消自选
                </el-button>
                <el-button
                  v-else
                  type="primary"
                  size="small"
                  plain
                  @click.stop="toggleFavorite(row.code)"
                >
                  加入自选
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <el-empty v-else :description="emptyDescription" />

        <!-- 浮动对比按钮 -->
        <transition name="el-fade-in">
          <div v-if="selectedCodes.length" class="compare-fab">
            <span>已选 {{ selectedCodes.length }} / {{ MAX_COMPARE }}</span>
            <el-button
              type="primary"
              :disabled="selectedCodes.length < 2"
              @click="openCompare"
            >
              对比 ({{ selectedCodes.length }})
            </el-button>
            <el-button @click="clearSelection">清空</el-button>
          </div>
        </transition>

        <!-- 对比 Dialog -->
        <el-dialog
          v-model="compareDialogVisible"
          :title="`基金对比 (${compareDataList.length} 只)`"
          width="90%"
          top="5vh"
          destroy-on-close
          @closed="onCompareDialogClosed"
        >
          <template v-if="loadingCompare">
            <div class="loading-overlay">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>正在加载对比数据...</span>
            </div>
          </template>
          <template v-else-if="compareDataList.length">
            <!-- 选中基金名 chips -->
            <div class="compare-chips">
              <el-tag
                v-for="(item, idx) in compareDataList"
                :key="item.code"
                :color="chipColor(idx)"
                style="color: white; margin-right: 8px; margin-bottom: 8px"
                closable
                @close="removeFromCompare(item.code)"
              >
                {{ item.code }} {{ item.name }}
              </el-tag>
            </div>

            <!-- 1. 指标对比表 -->
            <h3 class="compare-section-title">关键指标</h3>
            <el-table :data="compareTableData" stripe size="small">
              <el-table-column prop="name" label="指标" width="160" fixed />
              <el-table-column
                v-for="(item, idx) in compareDataList"
                :key="item.code"
                :label="shortName(item.name)"
                min-width="120"
                align="right"
              >
                <template #header>
                  <div :style="{ color: chipColor(idx) }">{{ shortName(item.name) }}</div>
                </template>
                <template #default="{ row }">
                  <span v-if="row.values[idx] !== null && row.values[idx] !== undefined">
                    {{ formatCompareValue(row.values[idx], row.metricKey) }}
                  </span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>

            <!-- 2. 雷达图叠加 -->
            <h3 class="compare-section-title">能力维度</h3>
            <div ref="compareRadarRef" style="width: 100%; height: 360px"></div>

            <!-- 3. 净值曲线叠加 -->
            <h3 class="compare-section-title">历史净值</h3>
            <el-radio-group v-model="comparePeriod" size="small" @change="renderCompareLineChart">
              <el-radio-button label="1y">近1年</el-radio-button>
              <el-radio-button label="3y">近3年</el-radio-button>
              <el-radio-button label="5y">近5年</el-radio-button>
            </el-radio-group>
            <div ref="compareLineRef" style="width: 100%; height: 360px; margin-top: 12px"></div>
          </template>
        </el-dialog>
      </template>

      <!-- 详情视图 -->
      <template v-else>
        <div class="detail-header">
          <el-button @click="backToList">
            <el-icon><ArrowLeft /></el-icon>
            返回自选
          </el-button>
          <div class="detail-actions">
            <el-button
              v-if="isFavorite"
              type="danger"
              plain
              @click="removeFromFavorites(fundCode)"
            >
              取消自选
            </el-button>
            <el-button
              v-else
              type="primary"
              @click="addToFavorites(fundCode)"
            >
              加入自选
            </el-button>
            <el-button type="success" :loading="refreshing" @click="manualRefresh" :disabled="!fundCode">
              <el-icon><Refresh /></el-icon>
              更新数据
            </el-button>
          </div>
        </div>

        <div v-if="fundData" style="margin-top: 20px">
          <!-- 基金基本信息卡片 -->
          <div class="info-card">
            <div class="info-header">
              <span class="fund-name">{{ fundData.name }}</span>
              <span class="fund-code">{{ fundData.code }}</span>
              <span v-if="fundInfo.fund_type" class="fund-type">
                {{ fundTypeLabel(fundInfo.fund_type) }}
              </span>
            </div>
            <div class="info-grid">
              <div class="info-item">
                <span class="info-label">基金经理</span>
                <span class="info-value">{{ fundInfo.manager || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">基金经理任期</span>
                <span class="info-value">{{ fundInfo.manager_exp || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">基金规模</span>
                <span class="info-value">{{ fundInfo.scale || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">成立日期</span>
                <span class="info-value">{{ fundInfo.found_date || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">管理费率</span>
                <span class="info-value">{{ fundInfo.m_fee || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">托管费率</span>
                <span class="info-value">{{ fundInfo.t_fee || '-' }}</span>
              </div>
            </div>
          </div>

          <!-- 评分和雷达图 -->
          <el-row :gutter="20" class="score-section">
            <el-col :span="6">
              <div class="score-card">
                <div class="score-label">综合评分</div>
                <div class="score-value" :class="getScoreClass(fundData.score)">
                  {{ fundData.score }}
                </div>
                <div class="score-desc">{{ getScoreDesc(fundData.score) }}</div>
              </div>
            </el-col>

            <el-col :span="10">
              <div ref="radarChartRef" style="width: 100%; height: 240px"></div>
            </el-col>

            <el-col :span="8">
              <div class="indicators-list">
                <div
                  v-for="ind in fundData.indicators"
                  :key="ind.name"
                  class="indicator-item"
                >
                  <span class="indicator-name">{{ ind.name }}</span>
                  <span class="indicator-value">
                    <template v-if="ind.value === null || ind.value === undefined">
                      <el-tag size="small" type="info">数据不足</el-tag>
                    </template>
                    <template v-else>
                      {{ formatValue(ind.value, ind.name) }}
                    </template>
                  </span>
                  <el-progress
                    v-if="ind.value !== null && ind.value !== undefined"
                    :percentage="ind.score"
                    :color="getProgressColor(ind.score)"
                    style="flex: 1"
                  />
                  <el-progress
                    v-else
                    :percentage="0"
                    :show-text="false"
                    style="flex: 1"
                  />
                </div>
              </div>
            </el-col>
          </el-row>

          <!-- 历史净值走势 -->
          <div class="chart-section">
            <div class="chart-header">
              <h3>历史净值走势</h3>
              <el-radio-group v-model="historyPeriod" size="small" @change="changePeriod">
                <el-radio-button label="1y">近1年</el-radio-button>
                <el-radio-button label="3y">近3年</el-radio-button>
                <el-radio-button label="5y">近5年</el-radio-button>
                <el-radio-button label="10y">近10年</el-radio-button>
              </el-radio-group>
            </div>
            <div ref="lineChartRef" style="width: 100%; height: 300px"></div>
          </div>
        </div>

        <div v-if="loading || refreshing" class="loading-overlay">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>{{ refreshing ? '正在抓取最新数据，请稍候...' : '正在加载数据...' }}</span>
        </div>

        <el-empty v-else-if="!fundData && !loading" description="该基金暂无评测数据" />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Loading, Refresh, ArrowLeft, Search } from '@element-plus/icons-vue'
import { fundApi } from '@/api'

const MAX_COMPARE = 5
const CHIP_COLORS = ['#409EFF', '#67c23a', '#e6a23c', '#f56c6c', '#909399']

const currentView = ref<'list' | 'detail'>('list')
const fundCode = ref('')
const searchKeyword = ref('')
const activeTab = ref<'favorites' | 'all'>('favorites')
const favoriteFunds = ref<any[]>([])
const evaluatedFunds = ref<any[]>([])
const favoriteCodeSet = computed(() => new Set(favoriteFunds.value.map(f => f.code)))
const isFavorite = ref(false)
const loading = ref(false)
const refreshing = ref(false)
const fundData = ref<any>(null)
const fundInfo = ref<any>({})
const historyData = ref<any[]>([])
const historyPeriod = ref('1y')

// 对比状态
const tableRef = ref<any>()
const selectedCodes = ref<string[]>([])
const compareDialogVisible = ref(false)
const loadingCompare = ref(false)
const compareDataList = ref<any[]>([])  // 每只基金的 eval 完整数据
const comparePeriod = ref('1y')
const compareHistoryMap = ref<Record<string, any[]>>({})
const compareRadarRef = ref<HTMLElement>()
const compareLineRef = ref<HTMLElement>()

const displayFunds = computed(() => {
  if (activeTab.value === 'favorites') return favoriteFunds.value
  return evaluatedFunds.value
})

const filteredFunds = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return displayFunds.value
  return displayFunds.value.filter(
    (f: any) => (f.name && f.name.toLowerCase().includes(kw))
              || (f.code && String(f.code).toLowerCase().includes(kw)),
  )
})

const emptyDescription = computed(() => {
  if (searchKeyword.value.trim()) return `未找到包含「${searchKeyword.value.trim()}」的基金`
  return activeTab.value === 'favorites' ? '暂无自选基金' : '暂无已评测基金'
})

const radarChartRef = ref<HTMLElement>()
const lineChartRef = ref<HTMLElement>()

const suggestedFunds = [
  { code: '161725', name: '招商中证白酒' },
  { code: '005827', name: '易方达蓝筹精选' },
  { code: '161039', name: '富国先进制造' },
  { code: '006228', name: '南方信息创新' },
  { code: '163406', name: '兴全合润分级' },
]

const fundTypeMap: Record<string, string> = {
  '001': '股票型', '002': '混合型', '003': '债券型',
  '004': '指数型', '005': 'ETF', '006': 'LOF', '007': 'QDII',
}
const fundTypeLabel = (code: string) => fundTypeMap[code] || code

const getScoreClass = (score: number) => {
  if (score >= 80) return 'score-excellent'
  if (score >= 60) return 'score-good'
  if (score >= 40) return 'score-normal'
  return 'score-poor'
}

const getScoreDesc = (score: number) => {
  if (score >= 80) return '优秀'
  if (score >= 60) return '良好'
  if (score >= 40) return '一般'
  return '较差'
}

const getProgressColor = (percentage: number) => {
  if (percentage >= 80) return '#67c23a'
  if (percentage >= 60) return '#85ce61'
  if (percentage >= 40) return '#e6a23c'
  return '#f56c6c'
}

const formatValue = (value: number, name: string) => {
  if (name.includes('收益')) return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
  if (name.includes('夏普') || name.includes('Sortino') || name.includes('卡玛')) return value.toFixed(2)
  if (name.includes('波动') || name.includes('回撤')) return `${value.toFixed(2)}%`
  if (name.includes('概率') || name.includes('百分位')) return `${value.toFixed(1)}%`
  return value.toFixed(2)
}

const loadFavorites = async () => {
  try {
    const res = await fundApi.getFavorites()
    favoriteFunds.value = res.data?.data || []
  } catch (error) {
    console.error('加载自选基金失败:', error)
  }
}

const loadEvaluatedFunds = async () => {
  try {
    const res = await fundApi.getEvaluated()
    evaluatedFunds.value = res.data?.data || []
  } catch (error) {
    console.error('加载已评测基金失败:', error)
  }
}

const addToFavorites = async (code: string) => {
  try {
    await fundApi.addFavorite(code)
    ElMessage.success('已加入自选')
    await loadFavorites()
    if (currentView.value === 'detail' && fundCode.value === code) {
      isFavorite.value = true
    }
  } catch (error) {
    console.error('加入自选失败:', error)
    ElMessage.error('加入自选失败')
  }
}

const removeFromFavorites = async (code: string) => {
  try {
    await fundApi.removeFavorite(code)
    ElMessage.success('已移除自选')
    await loadFavorites()
    if (currentView.value === 'detail' && fundCode.value === code) {
      isFavorite.value = false
    }
  } catch (error) {
    console.error('移除自选失败:', error)
    ElMessage.error('移除自选失败')
  }
}

const toggleFavorite = async (code: string) => {
  if (favoriteCodeSet.value.has(code)) {
    await removeFromFavorites(code)
  } else {
    await addToFavorites(code)
  }
}

const checkIsFavorite = async (code: string) => {
  try {
    const res = await fundApi.getFavorites()
    const list = res.data?.data || []
    isFavorite.value = list.some((f: any) => f.code === code)
  } catch (error) {
    isFavorite.value = false
  }
}

const handleEvaluate = () => {
  if (!fundCode.value.trim()) return
  viewDetail(fundCode.value.trim())
}

const viewDetail = async (code: string) => {
  fundCode.value = code
  currentView.value = 'detail'
  fundData.value = null
  fundInfo.value = {}
  historyData.value = []
  await checkIsFavorite(code)
  await evaluateFund()
}

const backToList = () => {
  currentView.value = 'list'
  fundCode.value = ''
  fundData.value = null
  fundInfo.value = {}
  historyData.value = []
}

const evaluateFund = async () => {
  if (!fundCode.value) return
  loading.value = true
  try {
    let evalRes
    try {
      evalRes = await fundApi.evaluate(fundCode.value)
    } catch (err: any) {
      if (err?.response?.status === 404) {
        // 未评测过 → 自动刷新（抓数据 + 写库）
        await fundApi.refreshEval(fundCode.value)
        evalRes = await fundApi.evaluate(fundCode.value)
      } else {
        throw err
      }
    }
    fundData.value = evalRes.data
    fundInfo.value = evalRes.data.info || {}
    await loadHistoryData()
    await nextTick()
    renderRadarChart()
    renderLineChart()
  } catch (error: any) {
    console.error('评测失败:', error)
    const msg = error?.response?.data?.detail || '评测失败，请检查基金代码'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

const manualRefresh = async () => {
  if (!fundCode.value) return
  refreshing.value = true
  try {
    await fundApi.refreshEval(fundCode.value)
    ElMessage.success('数据已更新')
    await evaluateFund()
  } catch (error: any) {
    console.error('刷新失败:', error)
    const msg = error?.response?.data?.detail || '刷新失败'
    ElMessage.error(msg)
  } finally {
    refreshing.value = false
  }
}

const loadHistoryData = async () => {
  try {
    const historyRes = await fundApi.getHistory(fundCode.value, historyPeriod.value)
    historyData.value = historyRes.data || []
  } catch (error) {
    console.error('获取历史数据失败:', error)
  }
}

const changePeriod = async () => {
  if (!fundCode.value) return
  await loadHistoryData()
  await nextTick()
  renderLineChart()
}

const renderRadarChart = () => {
  if (!radarChartRef.value || !fundData.value) return

  echarts.getInstanceByDom(radarChartRef.value)?.dispose()
  const chart = echarts.init(radarChartRef.value)
  const indicators = fundData.value.radar_data?.indicators || []

  chart.setOption({
    radar: {
      indicator: indicators.map((i: any) => ({ name: i.name, max: 100 })),
      radius: '65%',
      splitNumber: 4,
    },
    series: [{
      type: 'radar',
      data: [{
        value: indicators.map((i: any) => i.value),
        areaStyle: { color: 'rgba(102, 126, 234, 0.3)' },
        lineStyle: { color: '#667eea', width: 2 },
        itemStyle: { color: '#667eea' }
      }]
    }]
  })
}

const renderLineChart = () => {
  if (!lineChartRef.value || !historyData.value.length) return

  echarts.getInstanceByDom(lineChartRef.value)?.dispose()
  const chart = echarts.init(lineChartRef.value)
  const data = historyData.value.map((d: any) => ({
    date: d.date,
    nav: d.nav,
    accumulatedNav: d.accumulated_nav ?? d.nav
  }))

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        const item = data[p.dataIndex]
        return `${item.date}<br/>净值: ${item.nav}<br/>累计净值（复权）: ${item.accumulatedNav}`
      }
    },
    grid: { left: 60, right: 30, top: 30, bottom: 60 },
    xAxis: {
      type: 'category',
      data: data.map(d => d.date),
      boundaryGap: false,
      axisLabel: { fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      name: '累计净值（复权）',
      axisLabel: { fontSize: 11 }
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, bottom: 10 }
    ],
    series: [{
      name: '累计净值（复权）',
      type: 'line',
      data: data.map(d => d.accumulatedNav),
      smooth: true,
      areaStyle: { color: 'rgba(102, 126, 234, 0.2)' },
      lineStyle: { color: '#667eea', width: 2 },
      itemStyle: { color: '#667eea' }
    }]
  })
}

// ============ 对比功能 ============

const isRowSelectable = (row: any) => {
  // 已选中这只 OR 选中的 < MAX_COMPARE 仍可选
  if (selectedCodes.value.includes(row.code)) return true
  return selectedCodes.value.length < MAX_COMPARE
}

const onSelectionChange = (rows: any[]) => {
  selectedCodes.value = rows.map((r: any) => r.code)
}

const clearSelection = () => {
  selectedCodes.value = []
  tableRef.value?.clearSelection()
}

const removeFromCompare = (code: string) => {
  compareDataList.value = compareDataList.value.filter(it => it.code !== code)
  // 同步外层 table 里的勾选
  tableRef.value?.toggleRowSelection(
    filteredFunds.value.find((r: any) => r.code === code), false,
  )
}

const chipColor = (idx: number) => CHIP_COLORS[idx % CHIP_COLORS.length]
const shortName = (name: string) => (name && name.length > 4 ? name.slice(0, 4) : name)

// 指标对照表：行 = 指标名，列 = 各基金
const COMPARE_METRICS: { key: string; label: string; type: 'score' | 'return' | 'ratio' | 'pct2' }[] = [
  { key: 'score', label: '综合评分', type: 'score' },
  { key: 'return_1y', label: '近1年收益', type: 'return' },
  { key: 'return_3y', label: '近3年收益', type: 'return' },
  { key: 'return_5y', label: '近5年收益', type: 'return' },
  { key: 'sharpe', label: '夏普比率', type: 'ratio' },
  { key: 'sortino', label: 'Sortino比率', type: 'ratio' },
  { key: 'calmar', label: '卡玛比率', type: 'ratio' },
  { key: 'max_drawdown', label: '最大回撤', type: 'pct2' },
  { key: 'volatility', label: '年化波动率', type: 'pct2' },
  { key: 'profit_prob', label: '盈利概率', type: 'pct2' },
  { key: 'return_1y_pct', label: '同类1y百分位', type: 'pct2' },
]

const compareTableData = computed(() =>
  COMPARE_METRICS.map(m => ({
    name: m.label,
    metricKey: m.type,
    values: compareDataList.value.map(item => item[m.key] ?? null),
  })),
)

const formatCompareValue = (v: number, type: string) => {
  if (type === 'score') return v.toFixed(0)
  if (type === 'return') return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
  if (type === 'ratio') return v.toFixed(2)
  return `${v.toFixed(2)}%`
}

async function openCompare() {
  if (selectedCodes.value.length < 2) return
  compareDialogVisible.value = true
  loadingCompare.value = true
  compareDataList.value = []
  compareHistoryMap.value = {}
  try {
    // 并发拉每只基金的 eval
    const results = await Promise.all(
      selectedCodes.value.map(async (code) => {
        const res = await fundApi.evaluate(code)
        return { code, ...res.data }
      }),
    )
    compareDataList.value = results

    // 并发拉 1y 净值（默认）
    const period = comparePeriod.value
    const histories = await Promise.all(
      results.map(async (item) => {
        try {
          const h = await fundApi.getHistory(item.code, period)
          return { code: item.code, data: h.data || [] }
        } catch {
          return { code: item.code, data: [] }
        }
      }),
    )
    compareHistoryMap.value = Object.fromEntries(histories.map(h => [h.code, h.data]))

    await nextTick()
    renderCompareRadar()
    renderCompareLineChart()
  } catch (err) {
    console.error('加载对比数据失败:', err)
    ElMessage.error('加载对比数据失败')
  } finally {
    loadingCompare.value = false
  }
}

async function renderCompareRadar() {
  if (!compareRadarRef.value || !compareDataList.value.length) return
  echarts.getInstanceByDom(compareRadarRef.value)?.dispose()
  const chart = echarts.init(compareRadarRef.value)
  // 取第一只基金的指标维度作为基准
  const refIndicators = compareDataList.value[0]?.radar_data?.indicators || []
  const indicators = refIndicators.map((i: any) => ({ name: i.name, max: 100 }))

  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: {
      data: compareDataList.value.map((it: any) => shortName(it.name)),
      bottom: 0,
    },
    radar: { indicator: indicators, radius: '65%', splitNumber: 4 },
    series: [{
      type: 'radar',
      data: compareDataList.value.map((item: any, idx: number) => ({
        name: shortName(item.name),
        value: (item.radar_data?.indicators || []).map((i: any) => i.value),
        areaStyle: { color: chipColor(idx), opacity: 0.15 },
        lineStyle: { color: chipColor(idx), width: 2 },
        itemStyle: { color: chipColor(idx) },
      })),
    }],
  })
}

async function renderCompareLineChart() {
  if (!compareLineRef.value) return
  echarts.getInstanceByDom(compareLineRef.value)?.dispose()
  const chart = echarts.init(compareLineRef.value)

  // 切时间段时重新拉
  const period = comparePeriod.value
  if (Object.keys(compareHistoryMap.value).length
      && !compareHistoryMap.value[compareDataList.value[0]?.code]?.length) {
    // 已存在数据但全空说明之前拉过了空，按当前 period 不重新拉
  }
  // 简单策略：换 period 就重拉
  if (compareDataList.value.length
      && !compareHistoryMap.value[compareDataList.value[0]?.code]?.length) {
    try {
      const histories = await Promise.all(
        compareDataList.value.map(async (item: any) => {
          try {
            const h = await fundApi.getHistory(item.code, period)
            return { code: item.code, data: h.data || [] }
          } catch {
            return { code: item.code, data: [] }
          }
        }),
      )
      compareHistoryMap.value = Object.fromEntries(histories.map(h => [h.code, h.data]))
    } catch (err) {
      console.error('拉历史净值失败:', err)
    }
  }

  const xDates = (() => {
    const set = new Set<string>()
    Object.values(compareHistoryMap.value).forEach(arr =>
      arr.forEach((d: any) => d.date && set.add(d.date)),
    )
    return [...set].sort()
  })()

  const series = compareDataList.value.map((item: any, idx: number) => {
    const histArr = compareHistoryMap.value[item.code] || []
    const navMap = new Map(histArr.map((d: any) => [d.date, d.accumulated_nav ?? d.nav]))
    // 归一化：以首日累计净值 = 1
    let base: number | null = null
    const data = xDates.map(d => {
      const v = navMap.get(d)
      if (v == null) return null
      if (base == null) base = v
      return +(((v as number) / (base as number)) * 100).toFixed(2)
    })
    return {
      name: shortName(item.name),
      type: 'line',
      smooth: true,
      data,
      lineStyle: { color: chipColor(idx), width: 2 },
      itemStyle: { color: chipColor(idx) },
      connectNulls: true,
    }
  })

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: compareDataList.value.map((it: any) => shortName(it.name)), bottom: 0 },
    grid: { left: 60, right: 30, top: 30, bottom: 60 },
    xAxis: {
      type: 'category',
      data: xDates,
      boundaryGap: false,
      axisLabel: { fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: '首日归一 = 100',
      axisLabel: { fontSize: 11 },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, bottom: 10 },
    ],
    series,
  })
}

async function onCompareDialogClosed() {
  compareDataList.value = []
  compareHistoryMap.value = {}
  if (tableRef.value) {
    tableRef.value.clearSelection()
  }
  selectedCodes.value = []
}

onMounted(() => {
  loadFavorites()
  loadEvaluatedFunds()
  window.addEventListener('resize', () => {
    if (radarChartRef.value) echarts.getInstanceByDom(radarChartRef.value)?.resize()
    if (lineChartRef.value) echarts.getInstanceByDom(lineChartRef.value)?.resize()
    if (compareRadarRef.value) echarts.getInstanceByDom(compareRadarRef.value)?.resize()
    if (compareLineRef.value) echarts.getInstanceByDom(compareLineRef.value)?.resize()
  })
})
</script>

<style scoped>
.list-toolbar {
  margin-bottom: 20px;
  align-items: center;
}

.action-buttons {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.detail-actions {
  display: flex;
  gap: 8px;
}

.suggestions {
  margin-top: 12px;
  font-size: 13px;
  color: #909399;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.favorite-score {
  font-weight: bold;
}

.return-positive {
  color: #f56c6c;
}

.return-negative {
  color: #67c23a;
}

.info-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 20px;
  color: white;
  margin-bottom: 20px;
}

.info-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.fund-name {
  font-size: 20px;
  font-weight: bold;
}

.fund-code {
  font-size: 14px;
  opacity: 0.8;
  background: rgba(255, 255, 255, 0.2);
  padding: 2px 8px;
  border-radius: 4px;
}

.fund-type {
  font-size: 12px;
  opacity: 0.9;
  background: rgba(255, 255, 255, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 12px;
  opacity: 0.8;
}

.info-value {
  font-size: 14px;
  font-weight: 500;
}

.score-section {
  margin-bottom: 20px;
}

.score-card {
  text-align: center;
  padding: 24px 16px;
  background: #f9f9f9;
  border-radius: 12px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.score-label {
  font-size: 14px;
  color: #606266;
  margin-bottom: 8px;
}

.score-value {
  font-size: 56px;
  font-weight: bold;
}

.score-excellent { color: #67c23a; }
.score-good { color: #85ce61; }
.score-normal { color: #e6a23c; }
.score-poor { color: #f56c6c; }

.score-desc {
  font-size: 14px;
  color: #909399;
  margin-top: 8px;
}

.indicators-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  background: #f9f9f9;
  border-radius: 12px;
  max-height: 280px;
  overflow-y: auto;
}

.indicator-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.indicator-name {
  width: 80px;
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
}

.indicator-value {
  width: 70px;
  font-size: 13px;
  text-align: right;
  color: #303133;
  flex-shrink: 0;
}

.chart-section {
  padding: 20px;
  background: #f9f9f9;
  border-radius: 12px;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.chart-header h3 {
  margin: 0;
  font-size: 16px;
  color: #303133;
}

.loading-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  color: #909399;
  gap: 12px;
}

.loading-overlay .el-icon {
  font-size: 32px;
}

.compare-fab {
  position: fixed;
  right: 32px;
  bottom: 32px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 999px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  z-index: 2000;
}

.compare-fab span {
  font-size: 13px;
  color: #606266;
}

.compare-section-title {
  font-size: 14px;
  color: #606266;
  margin: 20px 0 10px 0;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}

.compare-chips {
  margin-bottom: 16px;
}
</style>
