<template>
  <div class="qdii-page">
    <div class="dashboard-card">
      <div class="section-header">
        <h2 class="section-title">QDII 场外基金限额监控</h2>
        <div class="header-actions">
          <el-button @click="hideStopped = !hideStopped" :type="hideStopped ? 'warning' : 'default'">
            <el-icon><Filter /></el-icon>
            {{ hideStopped ? '显示暂停' : '隐藏暂停' }}
          </el-button>
          <el-button type="primary" @click="manualRefresh" :loading="loading">
            <el-icon><Refresh /></el-icon>
            更新数据
          </el-button>
        </div>
      </div>

      <!-- 每日限额汇总 -->
      <div class="quota-summary">
        <div class="summary-row">
          <div class="summary-item-main">
            <span class="summary-label">每日限额汇总</span>
          </div>
          <div class="summary-values">
            <div v-if="sp500Total > 0" class="quota-tag sp500">
              标普500: {{ sp500Total }}元/天 ({{ sp500Count }}只)
            </div>
            <div v-if="ndxTotal > 0" class="quota-tag ndx">
              纳指100: {{ ndxTotal }}元/天 ({{ ndxCount }}只)
            </div>
            <div v-if="sp500Total === 0 && ndxTotal === 0" class="quota-tag empty">
              暂无有效限额
            </div>
          </div>
        </div>
      </div>

      <!-- 按分类展示（仅显示有明确限额的）-->
      <div v-for="group in groupedFundsWithLimit" :key="group.type" class="fund-group">
        <h3 class="group-title">
          {{ group.type }}（{{ group.funds.length }}只）
          <span class="group-total">限额: {{ group.total }}元/天</span>
        </h3>
        <el-table :data="group.funds" stripe size="small">
          <el-table-column prop="code" label="基金代码" width="90" />
          <el-table-column prop="name" label="基金名称" min-width="150" show-overflow-tooltip />
          <el-table-column prop="apply_status" label="申购状态" width="90">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.apply_status)" size="small">
                {{ row.apply_status || '-' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="limit_amount" label="每日限额" width="100">
            <template #default="{ row }">
              <el-tooltip
                v-if="isChanged(row.code)"
                :content="'上次: ' + getChangedOldValue(row.code)"
                placement="top"
              >
                <span :class="['limit-amount', 'changed', getLimitClass(row.limit_amount)]">
                  {{ row.limit_amount }}元
                  <el-icon class="change-icon"><WarningFilled /></el-icon>
                </span>
              </el-tooltip>
              <span v-else :class="['limit-amount', getLimitClass(row.limit_amount)]">
                {{ row.limit_amount }}元
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="redeem_status" label="赎回" width="80">
            <template #default="{ row }">
              <span :class="row.redeem_status === '开放赎回' ? 'text-green' : 'text-red'">
                {{ row.redeem_status || '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="scale" label="基金规模" width="90" show-overflow-tooltip />
          <el-table-column label="操作" width="70" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="showDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 汇总信息 -->
      <div class="summary-card">
        <el-row :gutter="16">
          <el-col :span="6">
            <div class="summary-item">
              <div class="summary-value text-red">{{ stopBuyCount }}</div>
              <div class="summary-label">暂停申购</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="summary-item">
              <div class="summary-value text-yellow">{{ limitCount }}</div>
              <div class="summary-label">限额购买</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="summary-item">
              <div class="summary-value text-green">{{ normalCount }}</div>
              <div class="summary-label">正常申购</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="summary-item">
              <div class="summary-value">{{ limitedCount }}</div>
              <div class="summary-label">可买</div>
            </div>
          </el-col>
        </el-row>
      </div>

      <!-- 基金详情弹窗 -->
      <el-dialog v-model="detailVisible" title="基金详情" width="500px">
        <div v-if="currentFund" class="detail-content">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="基金代码">{{ currentFund.code }}</el-descriptions-item>
            <el-descriptions-item label="基金类型">{{ currentFund.type }}</el-descriptions-item>
            <el-descriptions-item label="基金名称" :span="2">{{ currentFund.name }}</el-descriptions-item>

            <el-descriptions-item label="申购状态">
              <el-tag :type="getStatusType(currentFund.apply_status)" size="small">
                {{ currentFund.apply_status || '-' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="每日限额">
              <span :class="getLimitClass(currentFund.limit_amount)">
                {{ currentFund.limit_amount ? currentFund.limit_amount + '元' : '无限额' }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="赎回状态">
              <span :class="currentFund.redeem_status === '开放赎回' ? 'text-green' : 'text-red'">
                {{ currentFund.redeem_status || '-' }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="净值日期">{{ currentFund.nav_date || '-' }}</el-descriptions-item>

            <el-descriptions-item label="基金经理" :span="2">
              {{ currentFund.manager || '-' }}
              <span v-if="currentFund.manager_exp" class="text-gray"> ({{ currentFund.manager_exp }})</span>
            </el-descriptions-item>

            <el-descriptions-item label="成立日期">{{ currentFund.found_date || '-' }}</el-descriptions-item>
            <el-descriptions-item label="净值日期">{{ currentFund.nav_date || '-' }}</el-descriptions-item>
            <el-descriptions-item label="管理费率">{{ currentFund.m_fee || '-' }}</el-descriptions-item>
            <el-descriptions-item label="托管费率">{{ currentFund.t_fee || '-' }}</el-descriptions-item>
            <el-descriptions-item label="申购费率">{{ currentFund.buy_fee || '-' }}</el-descriptions-item>
            <el-descriptions-item label="赎回费率">{{ currentFund.redeem_fee || '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-dialog>

      <div class="info-tip">
        <el-icon><InfoFilled /></el-icon>
        <span>
          数据来源：东方财富F10 + 天天基金 | 更新于 {{ updateTime }}
          <br>
          暂停申购：无法购买 | 限额购买：每日有限额 | 正常申购：无限额购买
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Refresh, Filter, InfoFilled, WarningFilled } from '@element-plus/icons-vue'
import { qdiiApi } from '@/api'

interface Fund {
  code: string
  name: string
  type: string
  apply_status: string
  limit_amount: string
  redeem_status: string
  scale: string
  [key: string]: any
}

interface CacheData {
  [code: string]: {
    limit_amount: string
    apply_status: string
  }
}

const funds = ref<Fund[]>([])
const loading = ref(false)
const hideStopped = ref(false)
const updateTime = ref('')
const detailVisible = ref(false)
const currentFund = ref<Fund | null>(null)
const prevCache = ref<CacheData>({})

// 加载本地缓存
const loadCache = () => {
  try {
    const cached = localStorage.getItem('qdii_quota_cache')
    if (cached) {
      prevCache.value = JSON.parse(cached)
    }
  } catch (e) {
    console.error('加载缓存失败:', e)
  }
}

// 保存缓存到本地
const saveCache = () => {
  try {
    const cache: CacheData = {}
    for (const f of funds.value) {
      cache[f.code] = {
        limit_amount: f.limit_amount || '',
        apply_status: f.apply_status || '',
      }
    }
    localStorage.setItem('qdii_quota_cache', JSON.stringify(cache))
  } catch (e) {
    console.error('保存缓存失败:', e)
  }
}

// 检测限额变化的基金
const changedFunds = computed(() => {
  const changed: { code: string; name: string; old: string; new: string }[] = []
  for (const f of funds.value) {
    // 跳过暂停申购的
    if (f.apply_status === '暂停申购') continue

    const prev = prevCache.value[f.code]
    const prevLimit = prev?.limit_amount || ''
    const currLimit = f.limit_amount || ''

    // 检测变化：有值且与上次不同
    if (currLimit && currLimit !== prevLimit) {
      changed.push({
        code: f.code,
        name: simplifyName(f.name),
        old: prevLimit || '无限额',
        new: currLimit,
      })
    }
  }
  return changed
})

// 判断基金是否发生变化
const isChanged = (code: string) => {
  return changedFunds.value.some(f => f.code === code)
}

// 获取基金上次限额
const getChangedOldValue = (code: string) => {
  const fund = changedFunds.value.find(f => f.code === code)
  return fund ? fund.old + '元' : ''
}

// 简化基金名称
const simplifyName = (name: string) => {
  return name
    .replace(/\(QDII\)/g, '').replace('人民币', '')
    .replace('发起式联接', '联接').replace('发起联接', '联接')
    .replace('发起', '').replace('指数', '')
}

// 过滤有明确限额的基金
const filterWithLimit = (fundsList: Fund[]) => {
  return fundsList.filter(f =>
    f.apply_status !== '暂停申购' &&
    f.limit_amount &&
    !['无限额', '无', ''].includes(f.limit_amount)
  )
}

// 按分类分组的基金（仅显示有明确限额的；受 hideStopped 控制是否排除暂停申购）
const groupedFundsWithLimit = computed(() => {
  let filtered = funds.value.filter(f =>
    f.limit_amount &&
    !['无限额', '无', ''].includes(f.limit_amount)
  )
  if (hideStopped.value) {
    filtered = filtered.filter(f => f.apply_status !== '暂停申购')
  }
  const groups: Record<string, Fund[]> = {}

  for (const f of filtered) {
    const type = f.type || '其他'
    if (!groups[type]) groups[type] = []
    groups[type].push(f)
  }

  return Object.entries(groups).map(([type, fundList]) => ({
    type,
    funds: fundList,
    total: fundList.reduce((sum, f) => sum + (parseInt(f.limit_amount) || 0), 0),
  }))
})

// 统计数据
const sp500Funds = computed(() => {
  return filterWithLimit(funds.value.filter(f =>
    ['ETF联接基金', 'FOF基金', '股票指数/LOF'].includes(f.type)
  ))
})

const ndxFunds = computed(() => {
  return filterWithLimit(funds.value.filter(f =>
    ['纳指100 ETF联接', '纳指100 直接指数'].includes(f.type)
  ))
})

const sp500Total = computed(() => sp500Funds.value.reduce((sum, f) => sum + (parseInt(f.limit_amount) || 0), 0))
const sp500Count = computed(() => sp500Funds.value.length)
const ndxTotal = computed(() => ndxFunds.value.reduce((sum, f) => sum + (parseInt(f.limit_amount) || 0), 0))
const ndxCount = computed(() => ndxFunds.value.length)

const stopBuyCount = computed(() => funds.value.filter(f => f.apply_status === '暂停申购').length)
const limitCount = computed(() => filterWithLimit(funds.value).length)
const normalCount = computed(() => funds.value.filter(f => f.apply_status === '开放申购').length)
const limitedCount = computed(() => filterWithLimit(funds.value).length)

const getStatusType = (status: string) => {
  switch (status) {
    case '开放申购': return 'success'
    case '限大额': return 'warning'
    case '暂停申购': return 'danger'
    default: return 'info'
  }
}

const getLimitClass = (amount: string) => {
  if (!amount || ['无限额', '无'].includes(amount)) return 'text-green'
  const num = parseInt(amount)
  if (num <= 10) return 'text-red'
  if (num <= 100) return 'text-yellow'
  return ''
}

const formatTime = (time: string) => {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

const showDetail = (fund: Fund) => {
  currentFund.value = fund
  detailVisible.value = true
}

const refreshData = async () => {
  loading.value = true
  try {
    const res = await qdiiApi.getQuota()
    funds.value = res.data.funds || []
    updateTime.value = formatTime(res.data.update_time)
    if (funds.value.length > 0) {
      saveCache()
    }
  } catch (error) {
    console.error('读取失败:', error)
  } finally {
    loading.value = false
  }
}

// 手动重抓：触发后端爬虫并写入数据库
const manualRefresh = async () => {
  loading.value = true
  try {
    const res = await qdiiApi.refreshQuota()
    funds.value = res.data.funds || []
    updateTime.value = formatTime(res.data.update_time)
    saveCache()
  } catch (error) {
    console.error('刷新失败:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadCache()
  refreshData()
})
</script>

<style scoped>
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.quota-summary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
  color: white;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.summary-label {
  font-size: 14px;
  opacity: 0.9;
}

.summary-values {
  display: flex;
  gap: 16px;
}

.quota-tag {
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
}

.quota-tag.empty {
  opacity: 0.6;
}

.fund-group {
  margin-bottom: 24px;
}

.group-title {
  font-size: 14px;
  color: #606266;
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.group-total {
  font-size: 12px;
  color: #409eff;
  font-weight: normal;
}

.limit-amount {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.limit-amount.changed {
  background: #fff3e0;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #ff9800;
}

.change-icon {
  font-size: 12px;
  color: #ff9800;
}

.summary-card {
  background: #f9f9f9;
  border-radius: 8px;
  padding: 16px;
  margin-top: 16px;
}

.summary-item {
  text-align: center;
}

.summary-value {
  font-size: 28px;
  font-weight: bold;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.text-green { color: #67c23a; }
.text-red { color: #f56c6c; }
.text-yellow { color: #e6a23c; }
.text-gray { color: #909399; font-size: 12px; }

.detail-content {
  padding: 10px 0;
}

.info-tip {
  margin-top: 16px;
  padding: 12px;
  background: #f4f4f5;
  border-radius: 4px;
  color: #909399;
  font-size: 12px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
</style>
