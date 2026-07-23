import { ApiClient } from './request'
import type { 
  LoginForm, 
  RegisterForm, 
  LoginResponse, 
  RefreshTokenResponse,
  User,
  ChangePasswordForm
} from '@/types/auth'

export const authApi = {
  // 登录
  login: (data: LoginForm) =>
    ApiClient.post<LoginResponse>('/api/auth/login', data, {
      skipAuth: true,  // 登录请求不需要认证
      skipAuthError: true  // 跳过 401 错误的自动处理
    }),

  // 注册
  register: (data: RegisterForm) =>
    ApiClient.post('/api/auth/register', data, {
      skipAuth: true,  // 注册请求不需要认证
      skipAuthError: true  // 跳过 401 错误的自动处理
    }),

  // 登出
  logout: () =>
    ApiClient.post('/api/auth/logout'),

  // 刷新Token
  refreshToken: (refreshToken: string) =>
    ApiClient.post<RefreshTokenResponse>('/api/auth/refresh', { refresh_token: refreshToken }),

  // 获取用户信息
  getUserInfo: () =>
    ApiClient.get<User>('/api/auth/me'),

  // 获取用户权限（开源版不需要，admin拥有所有权限）
  // getUserPermissions: () =>
  //   ApiClient.get<UserPermissions>('/api/auth/permissions'),

  // 更新用户信息
  updateUserInfo: (data: Partial<User>) =>
    ApiClient.put<User>('/api/auth/me', data),

  // 修改密码
  changePassword: (data: ChangePasswordForm) =>
    ApiClient.post('/api/auth/change-password', data),

  // 重置密码
  resetPassword: (email: string) =>
    ApiClient.post('/api/auth/reset-password', { email }),

  // 验证邮箱
  verifyEmail: (token: string) =>
    ApiClient.post('/api/auth/verify-email', { token }),

  // ==================== 用户管理（管理员）====================

  // 获取用户列表
  listUsers: (skip = 0, limit = 100) =>
    ApiClient.get('/api/auth/users', { skip, limit }),

  // 创建用户
  createUser: (data: { username: string; email: string; password: string; is_admin?: boolean }) =>
    ApiClient.post('/api/auth/create-user', data),

  // 更新用户状态（激活/禁用、管理员权限、配额）
  updateUserStatus: (username: string, data: {
    is_active?: boolean
    is_admin?: boolean
    daily_quota?: number
    concurrent_limit?: number
  }) =>
    ApiClient.put(`/api/auth/users/${username}/status`, data),

  // 删除用户
  deleteUser: (username: string) =>
    ApiClient.delete(`/api/auth/users/${username}`),

  // 管理员重置用户密码
  adminResetPassword: (username: string, newPassword: string) =>
    ApiClient.post('/api/auth/reset-password', { username, new_password: newPassword }),
}
