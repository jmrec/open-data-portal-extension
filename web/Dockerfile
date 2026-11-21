FROM node:24-trixie-slim AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:24-trixie-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/dist ./dist
# Applied on first connection; they also seed BENECO's service area.
COPY --from=build /app/drizzle ./drizzle
ENV DATABASE_PATH=/app/data/beacon.sqlite
VOLUME /app/data
EXPOSE 3000
CMD ["node", "dist/server/index.mjs"]
