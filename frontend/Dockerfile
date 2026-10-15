FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:20-slim AS builder
WORKDIR /app
# next.config.mjs calls rewrites(), which Next evaluates at BUILD time and bakes
# into routes-manifest.json. Setting NEXT_PUBLIC_API_URL as a runtime `environment:`
# in docker-compose.yml is therefore too late: the built image keeps dialling the
# config's 127.0.0.1:8000 fallback (verified with `docker run -e ...`). It has to
# be present here instead, so compose passes it via `build.args`.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "run", "start"]
