# ---------- MindGlass 前端 Dockerfile ----------
FROM node:20-alpine AS build

WORKDIR /app

# 安装依赖
COPY package*.json ./
RUN npm install

# 构建
COPY ./ ./
RUN npm run build

# 生产阶段 — Nginx 服务
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
