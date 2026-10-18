FROM node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f
WORKDIR /opt/phyexp
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && chmod -R a+rX /opt/phyexp
USER node
ENV NODE_ENV=production HOME=/tmp/home
WORKDIR /work
ENTRYPOINT ["node"]
