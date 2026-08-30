<template>
  <div class="backtest-page">
    <div class="dashboard-card">
      <!-- Hero 区域 -->
      <div class="backtest-hero">
        <div class="hero-content">
          <div class="hero-icon">
            <el-icon :size="36" color="#fff"
><TrendCharts /></el-icon>
          </div>
          <div class="hero-text">
            <h2 class="hero-title">策略回测</h2>
            <p class="hero-desc">ETF 双动量轮动 · 定投策略 · 历史收益验证</p>
          </div>
        </div>
        <el-button class="run-btn-fancy" type="primary" @click="openParamDialog"
>
          <el-icon :size="20"><VideoPlay /></el-icon>
          <span>开始回测</span>
        </el-button>
      </div>

      <!-- 回测中提示 -->
      <div v-if="running" class="running-tip">
        <el-icon class="is-loading" size="18"><Loading /></el-icon>
        <span>回测计算中，请稍候...</span>
      </div>

      <!-- 参数设置弹窗 -->
      <el-dialog
        v-model="showParamDialog"
        title="策略参数设置"
        width="820px"
        :close-on-click-modal="false"
        destroy-on-close
      >
        <el-form :model="form" label-position="top" class="backtest-form compact">
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="策略">
                <el-select v-model="form.strategy_type" placeholder="选择策略" style="width: 100%">
                  <el-option
                    v-for="s in strategies"
                    :key="s.type"
                    :label="s.name"
                    :value="s.type"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="回测名称">
                <el-input v-model="form.name" placeholder="给这次回测起个名字" size="small" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="初始资金">
                <el-input-number v-model="form.params.initial_capital" :min="1000" :step="1000" size="small" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="开始日期">
                <el-date-picker v-model="form.params.start_date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="结束日期">
                <el-date-picker v-model="form.params.end_date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="空仓年化收益">
                <el-input-number
                  v-model="form.params.cash_rate"
                  :min="0"
                  :max="0.1"
                  :step="0.005"
                  :precision="3"
                  size="small"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="16">
              <el-form-item label="标的池">
                <el-input v-model="universeInput" placeholder="逗号分隔，如 159915,512890" size="small" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="基准代码">
                <el-input v-model="form.params.benchmark_code" placeholder="默认 510300" size="small" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 动态参数：根据策略 schema 渲染 -->
          <el-row :gutter="16">
            <el-col v-for="field in dynamicFields" :key="field.name" :span="8">
              <el-form-item :label="field.label">
                <template v-if="field.type === 'number'">
                  <el-input-number
                    v-model="form.params[field.name]"
                    :min="field.min"
                    :max="field.max"
                    :step="field.step"
                    :precision="getPrecision(field)"
                    size="small"
                    style="width: 100%"
                  />
                </template>
                <template v-else-if="field.type === 'select'">
                  <el-select v-model="form.params[field.name]" size="small" style="width: 100%">
                    <el-option
                      v-for="opt in field.options"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </template>
                <template v-else-if="field.type === 'boolean'">
                  <el-switch v-model="form.params[field.name]" size="small" />
                </template>
                <template v-else-if="field.type === 'list'">
                  <el-input
                    v-model="listInputs[field.name]"
                    :placeholder="field.description || '逗号分隔'"
                    size="small"
                  />
                </template>
                <template v-else>
                  <el-input v-model="form.params[field.name]" size="small" />
                </template>
                <div v-if="field.description" class="field-desc">{{ field.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <template #footer>
          <span class="dialog-footer">
            <el-button @click="showParamDialog = false">取消</el-button>
            <el-button type="primary" :loading="running" @click="startBacktest">开始回测</el-button>
          </span>
        </template>
      </el-dialog>

      <!-- 历史结果列表 -->
      <div class="section-header">
        <h3 class="section-subtitle">历史回测</h3>
        <div class="action-group">
          <el-button @click="loadRuns">刷新列表</el-button>
          <el-button
            type="danger"
            :disabled="selectedRuns.length === 0"
            plain
            @click="deleteSelectedRuns"
          >
            删除({{ selectedRuns.length }})
          </el-button>
          <el-button type="primary" :disabled="selectedRuns.length < 2" @click="compareRuns">
            对比选中({{ selectedRuns.length }})
          </el-button>
        </div>
      </div>

      <el-table
        :data="runs"
        stripe
        style="width: 100%"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="strategy_type" label="策略" width="130" />
        <el-table-column prop="start_date" label="开始" width="110" />
        <el-table-column prop="end_date" label="结束" width="110" />
        <el-table-column prop="total_return" label="累计收益" width="110" align="right">
          <template #default="{ row }">
            <span :class="row.total_return >= 0 ? 'return-positive' : 'return-negative'">
              {{ formatPct(row.total_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="cagr" label="年化收益" width="110" align="right">
          <template #default="{ row }">
            <span :class="row.cagr >= 0 ? 'return-positive' : 'return-negative'">
              {{ formatPct(row.cagr) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="max_drawdown" label="最大回撤" width="110" align="right">
          <template #default="{ row }">
            <span class="return-negative">
              {{ row.max_drawdown != null ? row.max_drawdown.toFixed(2) + '%' : '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="sharpe" label="夏普" width="90" align="right">
          <template #default="{ row }">
            {{ row.sharpe != null ? row.sharpe.toFixed(2) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="annual_volatility" label="年化波动" width="110" align="right">
          <template #default="{ row }">
            {{ row.annual_volatility != null ? row.annual_volatility.toFixed(2) + '%' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="win_rate" label="胜率" width="90" align="right">
          <template #default="{ row }">
            {{ row.win_rate != null ? row.win_rate.toFixed(2) + '%' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="total_trades" label="交易数" width="90" align="right" />
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="viewRun(row)">查看</el-button>
            <el-button type="danger" size="small" plain @click="deleteRun(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 选中结果详情 -->
      <div v-if="currentRun" class="detail-section">
        <h3 class="section-subtitle">{{ currentRun.name }} 回测详情</h3>

        <el-row :gutter="16" class="metric-cards">
          <el-col :span="4" v-for="m in metricItems" :key="m.key">
            <div class="metric-card">
              <div class="metric-label">{{ m.label }}</div>
              <div class="metric-value" :class="m.classFn ? m.classFn(currentRun[m.key]) : ''">
                {{ m.format(currentRun[m.key]) }}
              </div>
            </div>
          </el-col>
        </el-row>

        <el-row :gutter="20" class="charts-row">
          <el-col :span="12">
            <div ref="equityChartRef" style="width: 100%; height: 360px"></div>
          </el-col>
          <el-col :span="12">
            <div ref="drawdownChartRef" style="width: 100%; height: 360px"></div>
          </el-col>
        </el-row>
      </div>

      <!-- 对比视图 -->
      <div v-if="compareData" class="detail-section">
        <h3 class="section-subtitle">对比结果</h3>
        <div ref="compareChartRef" style="width: 100%; height: 400px"></div>
        <el-table :data="compareData.runs" stripe style="width: 100%; margin-top: 16px">
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="total_return" label="累计收益" align="right">
            <template #default="{ row }">
              <span :class="row.total_return >= 0 ? 'return-positive' : 'return-negative'">
                {{ formatPct(row.total_return) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="cagr" label="年化收益" align="right">
            <template #default="{ row }">
              <span :class="row.cagr >= 0 ? 'return-positive' : 'return-negative'">
                {{ formatPct(row.cagr) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="max_drawdown" label="最大回撤" align="right">
            <template #default="{ row }">
              <span class="return-negative">
                {{ row.max_drawdown != null ? row.max_drawdown.toFixed(2) + '%' : '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="sharpe" label="夏普" align="right">
            <template #default="{ row }">
              {{ row.sharpe != null ? row.sharpe.toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="win_rate" label="胜率" align="right">
            <template #default="{ row }">
              {{ row.win_rate != null ? row.win_rate.toFixed(2) + '%' : '-' }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, VideoPlay, TrendCharts } from '@element-plus/icons-vue'
import { backtestApi } from '@/api'

const strategies = ref<any[]>([])
const runs = ref<any[]>([])
const currentRun = ref<any>(null)
const equityData = ref<any[]>([])
const selectedRuns = ref<any[]>([])
const compareData = ref<any>(null)
const running = ref(false)
const showParamDialog = ref(false)

const equityChartRef = ref<HTMLElement | null>(null)
const drawdownChartRef = ref<HTMLElement | null>(null)
const compareChartRef = ref<HTMLElement | null>(null)

const form = reactive<any>({
  strategy_type: 'etf_dual_momentum',
  name: '',
  params: {
    initial_capital: 10000,
    cash_rate: 0.01,
    start_date: '2021-07-05',
    end_date: '2026-07-02',
    benchmark_code: '510300',
    universe: ['159915', '512890', '159941', '518880'],
  }
})

const universeInput = computed({
  get: () => form.params.universe?.join(',') || '',
  set: (val: string) => {
    form.params.universe = val.split(',').map((s: string) => s.trim()).filter(Boolean)
  }
})

const listInputs = reactive<Record<string, string>>({})

const dynamicFields = computed(() => {
  const strategy = strategies.value.find((s: any) => s.type === form.strategy_type)
  if (!strategy) return []
  // 过滤掉已经在固定表单中的字段
  const fixed = new Set(['initial_capital', 'cash_rate', 'start_date', 'end_date', 'benchmark_code', 'universe'])
  return strategy.params_schema.filter((f: any) => !fixed.has(f.name))
})

const metricItems = [
  { key: 'total_return', label: '累计收益', format: (v: number) => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '-', classFn: (v: number) => v != null && v >= 0 ? 'return-positive' : 'return-negative' },
  { key: 'cagr', label: '年化收益', format: (v: number) => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '-', classFn: (v: number) => v != null && v >= 0 ? 'return-positive' : 'return-negative' },
  { key: 'benchmark_total_return', label: '基准收益', format: (v: number) => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '-', classFn: (v: number) => v != null && v >= 0 ? 'return-positive' : 'return-negative' },
  { key: 'alpha', label: '超额收益', format: (v: number) => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '-', classFn: (v: number) => v != null && v >= 0 ? 'return-positive' : 'return-negative' },
  { key: 'max_drawdown', label: '最大回撤', format: (v: number) => v != null ? `${v.toFixed(2)}%` : '-', classFn: () => 'return-negative' },
  { key: 'sharpe', label: '夏普比率', format: (v: number) => v != null ? v.toFixed(2) : '-' },
  { key: 'annual_volatility', label: '年化波动', format: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
  { key: 'win_rate', label: '胜率', format: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
  { key: 'profit_loss_ratio', label: '盈亏比', format: (v: number) => v != null ? v.toFixed(2) : '-' },
  { key: 'total_trades', label: '交易次数', format: (v: number) => v != null ? v : '-' },
  { key: 'max_consecutive_losing_days', label: '最大连亏天数', format: (v: number) => v != null ? v : '-' },
  { key: 'cash_position_days_ratio', label: '空仓占比', format: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
]

const formatPct = (v?: number) => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '-'

const getPrecision = (field: any) => {
  if (field.step === undefined || field.step === null) return 2
  if (field.step >= 1) return 0
  if (field.step >= 0.01) return 2
  return 4
}

const loadStrategies = async () => {
  try {
    const res = await backtestApi.getStrategies()
    strategies.value = res.data
    if (strategies.value.length) {
      applySchemaDefaults(strategies.value[0])
    }
  } catch (error: any) {
    ElMessage.error('加载策略失败')
  }
}

const applySchemaDefaults = (strategy: any) => {
  const defaults: any = {}
  for (const field of strategy.params_schema) {
    defaults[field.name] = field.default
  }
  form.params = defaults

  // 清空并重新填充 list 类型输入框
  for (const key of Object.keys(listInputs)) {
    delete listInputs[key]
  }
  for (const field of strategy.params_schema) {
    if (field.type === 'list' && Array.isArray(field.default)) {
      listInputs[field.name] = field.default.join(',')
    }
  }
}

watch(() => form.strategy_type, (type) => {
  const strategy = strategies.value.find((s: any) => s.type === type)
  if (strategy) applySchemaDefaults(strategy)
})

const loadRuns = async () => {
  try {
    const res = await backtestApi.getRuns()
    runs.value = res.data
  } catch (error: any) {
    ElMessage.error('加载回测列表失败')
  }
}

const openParamDialog = () => {
  showParamDialog.value = true
}

const startBacktest = async () => {
  showParamDialog.value = false
  await runBacktest()
}

const runBacktest = async () => {
  running.value = true
  try {
    const params = { ...form.params }
    // 处理 list 类型输入
    const strategy = strategies.value.find((s: any) => s.type === form.strategy_type)
    if (strategy) {
      for (const field of strategy.params_schema) {
        if (field.type === 'list' && listInputs[field.name]) {
          params[field.name] = listInputs[field.name].split(',').map((s: string) => s.trim()).filter(Boolean)
        }
      }
    }

    const res = await backtestApi.runBacktest({
      strategy_type: form.strategy_type,
      name: form.name || undefined,
      params,
    })
    ElMessage.success('回测完成')
    await loadRuns()
    await viewRun(res.data)
  } catch (error: any) {
    const msg = error?.response?.data?.detail || '回测失败'
    ElMessage.error(msg)
  } finally {
    running.value = false
  }
}

const viewRun = async (row: any) => {
  currentRun.value = row
  compareData.value = null
  try {
    const [detailRes, equityRes] = await Promise.all([
      backtestApi.getRun(row.id),
      backtestApi.getEquity(row.id),
    ])
    currentRun.value = detailRes.data
    equityData.value = equityRes.data
    nextTick(() => {
      renderEquityChart()
      renderDrawdownChart()
    })
  } catch (error: any) {
    ElMessage.error('加载详情失败')
  }
}

const deleteRun = async (id: number) => {
  try {
    await ElMessageBox.confirm('确定删除这条回测记录吗？', '提示', { type: 'warning' })
    await backtestApi.deleteRun(id)
    ElMessage.success('删除成功')
    if (currentRun.value?.id === id) {
      currentRun.value = null
      equityData.value = []
    }
    await loadRuns()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const deleteSelectedRuns = async () => {
  if (selectedRuns.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedRuns.value.length} 条回测记录吗？`,
      '提示',
      { type: 'warning' }
    )
    const ids = selectedRuns.value.map((r: any) => r.id)
    for (const id of ids) {
      await backtestApi.deleteRun(id)
    }
    ElMessage.success(`已删除 ${ids.length} 条记录`)
    selectedRuns.value = []
    currentRun.value = null
    equityData.value = []
    compareData.value = null
    await loadRuns()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('批量删除失败')
    }
  }
}

const handleSelectionChange = (selection: any[]) => {
  selectedRuns.value = selection
}

const compareRuns = async () => {
  try {
    const ids = selectedRuns.value.map((r: any) => r.id)
    const res = await backtestApi.compareRuns(ids)
    compareData.value = res.data
    nextTick(() => renderCompareChart())
  } catch (error: any) {
    ElMessage.error('对比失败')
  }
}

const renderEquityChart = () => {
  if (!equityChartRef.value || !equityData.value.length) return
  echarts.getInstanceByDom(equityChartRef.value)?.dispose()
  const chart = echarts.init(equityChartRef.value)
  const dates = equityData.value.map((d: any) => d.date)
  chart.setOption({
    title: { text: '净值曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['组合净值', '基准净值'], bottom: 0 },
    grid: { left: 60, right: 30, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', name: '净值' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 20 }],
    series: [
      {
        name: '组合净值',
        type: 'line',
        data: equityData.value.map((d: any) => d.portfolio_value),
        smooth: true,
        lineStyle: { color: '#667eea', width: 2 },
        itemStyle: { color: '#667eea' },
      },
      {
        name: '基准净值',
        type: 'line',
        data: equityData.value.map((d: any) => d.benchmark_value),
        smooth: true,
        lineStyle: { color: '#f56c6c', width: 2 },
        itemStyle: { color: '#f56c6c' },
      }
    ]
  })
}

const renderDrawdownChart = () => {
  if (!drawdownChartRef.value || !equityData.value.length) return
  echarts.getInstanceByDom(drawdownChartRef.value)?.dispose()
  const chart = echarts.init(drawdownChartRef.value)
  const dates = equityData.value.map((d: any) => d.date)
  chart.setOption({
    title: { text: '回撤曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0].axisValue}<br/>回撤: ${p[0].value?.toFixed(2)}%` },
    grid: { left: 60, right: 30, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', name: '回撤(%)', max: 0 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 20 }],
    series: [{
      type: 'line',
      data: equityData.value.map((d: any) => d.drawdown),
      areaStyle: { color: 'rgba(245, 108, 111, 0.3)' },
      lineStyle: { color: '#f56c6c' },
      itemStyle: { color: '#f56c6c' },
      smooth: true,
    }]
  })
}

const renderCompareChart = () => {
  if (!compareChartRef.value || !compareData.value) return
  echarts.getInstanceByDom(compareChartRef.value)?.dispose()
  const chart = echarts.init(compareChartRef.value)
  const dates = compareData.value.dates
  const series = compareData.value.runs.map((run: any) => ({
    name: run.name,
    type: 'line',
    data: compareData.value.equity_series[String(run.id)],
    smooth: true,
  }))
  chart.setOption({
    title: { text: '多策略净值对比', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: compareData.value.runs.map((r: any) => r.name), bottom: 0 },
    grid: { left: 60, right: 30, top: 40, bottom: 60 },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', name: '净值' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 40 }],
    series,
  })
}

onMounted(() => {
  loadStrategies()
  loadRuns()
  window.addEventListener('resize', () => {
    if (equityChartRef.value) echarts.getInstanceByDom(equityChartRef.value)?.resize()
    if (drawdownChartRef.value) echarts.getInstanceByDom(drawdownChartRef.value)?.resize()
    if (compareChartRef.value) echarts.getInstanceByDom(compareChartRef.value)?.resize()
  })
})
</script>

<style scoped>
.backtest-page {
  padding: 20px;
}

.param-section {
  margin-bottom: 24px;
}

.backtest-form {
  background: #f8f9fa;
  padding: 20px;
  border-radius: 12px;
}

.field-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 24px 0 16px;
}

.section-subtitle {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.detail-section {
  margin-top: 24px;
}

.metric-cards {
  margin-bottom: 20px;
}

.metric-card {
  background: #fff;
  border-radius: 8px;
  padding: 16px 8px;
  text-align: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}

.metric-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
}

.metric-value {
  font-size: 20px;
  font-weight: 600;
}

.charts-row {
  margin-top: 20px;
}

.backtest-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 28px;
  margin-bottom: 24px;
  border-radius: 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.25);
}

.hero-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.hero-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(4px);
}

.hero-title {
  margin: 0 0 4px;
  font-size: 24px;
  font-weight: 700;
  color: #fff;
}

.hero-desc {
  margin: 0;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.85);
}

.run-btn-fancy {
  height: 48px;
  padding: 0 28px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 12px;
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  border: none;
  box-shadow: 0 6px 16px rgba(245, 87, 108, 0.35);
  transition: all 0.3s ease;
}

.run-btn-fancy:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(245, 87, 108, 0.45);
}

.run-btn-fancy .el-icon {
  margin-right: 8px;
}

.backtest-form.compact :deep(.el-form-item) {
  margin-bottom: 12px;
}

.backtest-form.compact :deep(.el-form-item__label) {
  padding-bottom: 4px;
  line-height: 1.2;
  font-size: 13px;
}

.running-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: #ecf5ff;
  border-radius: 8px;
  color: #409eff;
  font-size: 14px;
}

.action-group {
  display: flex;
  gap: 8px;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.return-positive {
  color: #67c23a;
}

.return-negative {
  color: #f56c6c;
}
</style>
