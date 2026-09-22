# The static site, the prerender job, and the /api hop that keeps the browser
# on one origin.
#
# Three stages. pnpm builds the app twice (the browser bundle and the server
# bundle the prerenderer imports); the prerender stage is that build plus node,
# run at each deploy and each night against the API to write one HTML file per
# page; nginx serves the files. Node never serves a request: the VPS runs nginx
# and a job, not a server.
#
# BUILD_ID names the deploy (the short commit sha). It is baked into both the
# nginx stage, which reads its pages from /pages/<BUILD_ID>, and the prerender
# stage, which writes them there, so the two can only ever agree, whatever
# environment a later `docker compose up` or `run` happens to have.

FROM node:22-alpine AS build
WORKDIR /app
ARG BUILD_ID=dev
ENV BUILD_ID=${BUILD_ID}

# corepack ships with node 22 and reads packageManager from package.json, so the
# pnpm version is pinned by the repository rather than by this file.
RUN corepack enable

# The lockfile layer, which only changes when a dependency does.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# `pnpm build` is `tsc -b && vite build && vite build --ssr ...`: a type error
# fails the image build, which is exactly where it should fail.
RUN pnpm build


# The prerender job. Reads the API on the compose network, writes the pages
# volume; see prerender/run.mjs.
FROM build AS prerender
ENV API_BASE=http://api:8000 \
    PRERENDER_OUT=/pages
CMD ["node", "prerender/run.mjs"]


FROM nginx:1.27-alpine
ARG BUILD_ID=dev
ENV BUILD_ID=${BUILD_ID}
COPY --from=build /app/dist /usr/share/nginx/html
# The server bundle is the prerenderer's, not a file to serve; /pages is where
# the volume mounts.
RUN rm -rf /usr/share/nginx/html/server /usr/share/nginx/html/pages
# A template rather than a config: the image substitutes ${BUILD_ID} at start.
COPY nginx.conf /etc/nginx/templates/default.conf.template

EXPOSE 80
