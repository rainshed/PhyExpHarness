FROM node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f
WORKDIR /opt/phyexp
COPY package.json package-lock.json ./
COPY npm-packages/ /tmp/npm-packages/
RUN --network=none npm cache add /tmp/npm-packages/*.tgz --cache /tmp/npm-cache --offline --ignore-scripts && \
    npm ci --cache /tmp/npm-cache --offline --ignore-scripts --no-audit --no-fund && \
    rm -rf /tmp/npm-packages /tmp/npm-cache && chmod -R a+rX /opt/phyexp
# The host fetches only the exact Debian files in development-dependencies.json
# and verifies their SHA-256 before staging this credential-free build context.
COPY development/ /tmp/meta-debs/
RUN --network=none DEBIAN_FRONTEND=noninteractive apt-get --yes --no-install-recommends --allow-downgrades install /tmp/meta-debs/*.deb && \
    dpkg-query -W > /opt/meta-development-packages.lock && rm -rf /tmp/meta-debs
USER node
ENV NODE_ENV=production HOME=/tmp/home
WORKDIR /work
ENTRYPOINT ["node"]
