FROM maven:3.9.9-eclipse-temurin-17 AS build

WORKDIR /workspace
COPY pom.xml ./
COPY mvnw ./
COPY .mvn ./.mvn
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash codeagentx \
    && mkdir -p /workspaces \
    && chown -R codeagentx:codeagentx /app /workspaces

RUN existing_user="$(getent passwd 1000 | cut -d: -f1 || true)" \
    && if [ -n "$existing_user" ] && [ "$existing_user" != "codeagentx" ]; then userdel -r "$existing_user" 2>/dev/null || userdel "$existing_user"; fi \
    && if ! getent group 1000 >/dev/null; then groupadd --gid 1000 codeagentx-shared; fi \
    && usermod --uid 1000 --gid 1000 codeagentx \
    && chown -R 1000:1000 /app /workspaces /home/codeagentx

COPY --from=build /workspace/target/control-plane-0.1.0-SNAPSHOT.jar /app/control-plane.jar

USER codeagentx

EXPOSE 8080

CMD ["java", "-jar", "/app/control-plane.jar"]
