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

RUN groupmod --gid 1000 codeagentx \
    && usermod --uid 1000 --gid 1000 codeagentx \
    && chown -R codeagentx:codeagentx /app /workspaces /home/codeagentx

COPY --from=build /workspace/target/control-plane-0.1.0-SNAPSHOT.jar /app/control-plane.jar

USER codeagentx

EXPOSE 8080

CMD ["java", "-jar", "/app/control-plane.jar"]
