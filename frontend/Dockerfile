FROM node:24-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/
COPY widget/package.json ./widget/
RUN npm ci
COPY frontend ./frontend
COPY widget ./widget
RUN npm run build
FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/frontend/dist /usr/share/nginx/html
COPY --from=build /build/widget/dist /usr/share/nginx/html/widget
EXPOSE 80
