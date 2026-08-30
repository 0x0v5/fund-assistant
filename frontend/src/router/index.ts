import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: Home
    },
    {
      path: '/qdii',
      name: 'qdii',
      component: () => import('@/views/Qdii.vue')
    },
    {
      path: '/fund-eval',
      name: 'fund-eval',
      component: () => import('@/views/FundEval.vue')
    },
    {
      path: '/etf-momentum',
      name: 'etf-momentum',
      component: () => import('@/views/EtfMomentum.vue')
    },
    {
      path: '/industry',
      name: 'industry',
      component: () => import('@/views/Industry.vue')
    },
    {
      path: '/backtest',
      name: 'backtest',
      component: () => import('@/views/Backtest.vue')
    }
  ]
})

export default router
