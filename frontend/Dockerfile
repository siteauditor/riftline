# The static site, plus the /api hop that keeps the browser on one origin.
#
# Two stages: pnpm builds the bundle, nginx serves it. Node never reaches the
# server, which is the other reason this is containerised: the VPS has no node
# and does not need one.

FROM node:22-alpine AS build
WORKDIR /app

# corepack ships with node 22 and reads packageManager from package.json, so the
# pnpm version is pinned by the repository rather than by this file.
RUN corepack enable

# The lockfile layer, which only changes when a dependency does.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# `pnpm build` is `tsc -b && vite build`: a type error fails the image build,
# which is exactly where it should fail.
RUN pnpm build


FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
