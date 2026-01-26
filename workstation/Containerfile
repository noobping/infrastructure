FROM quay.io/fedora/fedora-coreos:stable
RUN rpm-ostree install -y cachefilesd && \
    rm -rf /var/cache/* && \
    ostree container commit
COPY cachefilesd.conf /etc/cachefilesd.conf
RUN ostree container commit
