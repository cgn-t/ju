# JUMBO demo Jenkins — eklentiler + jq/curl/openssl + ns-deploy.sh + JCasC gömülü.
# Setup sihirbazı kapalı; JCasC ile admin/jumbo kullanıcıları, vault-token, netscaler-deploy job'u gelir.
FROM jenkins/jenkins:lts

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends jq curl openssl \
 && rm -rf /var/lib/apt/lists/*
COPY ns-deploy.sh /usr/local/bin/ns-deploy.sh
RUN chmod +x /usr/local/bin/ns-deploy.sh
USER jenkins

# Eklentileri kur
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli -f /usr/share/jenkins/ref/plugins.txt

# Setup sihirbazını atla + JCasC yolunu göster
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
ENV CASC_JENKINS_CONFIG=/var/jenkins_conf/jenkins.yaml
COPY jenkins.yaml /var/jenkins_conf/jenkins.yaml
