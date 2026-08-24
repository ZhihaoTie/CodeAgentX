package com.codeagentx.controlplane.workflow;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.TaskExecutor;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

@Configuration
public class RunWorkerConfig {
    @Bean
    public TaskExecutor agentRunExecutor(
        @Value("${codeagentx.worker.core-pool-size:2}") int corePoolSize,
        @Value("${codeagentx.worker.max-pool-size:2}") int maxPoolSize,
        @Value("${codeagentx.worker.queue-capacity:100}") int queueCapacity
    ) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("agent-run-");
        executor.setCorePoolSize(corePoolSize);
        executor.setMaxPoolSize(maxPoolSize);
        executor.setQueueCapacity(queueCapacity);
        executor.initialize();
        return executor;
    }
}
