package com.codeagentx.controlplane.events;

import com.codeagentx.controlplane.domain.RunEventRecord;
import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;

@Component
public class RunEventStreamHub {
    private final List<RunSubscription> subscriptions = new CopyOnWriteArrayList<RunSubscription>();

    public SseEmitter subscribe(RunRecord run) throws IOException {
        SseEmitter emitter = new SseEmitter(0L);
        RunSubscription subscription = new RunSubscription(run.getRunId(), emitter);
        subscriptions.add(subscription);

        emitter.onCompletion(new Runnable() {
            @Override
            public void run() {
                subscriptions.remove(subscription);
            }
        });
        emitter.onTimeout(new Runnable() {
            @Override
            public void run() {
                subscriptions.remove(subscription);
            }
        });
        emitter.onError(new java.util.function.Consumer<Throwable>() {
            @Override
            public void accept(Throwable throwable) {
                subscriptions.remove(subscription);
            }
        });

        publishToSubscription(subscription, run);
        return emitter;
    }

    public void publish(RunRecord run) {
        for (RunSubscription subscription : subscriptions) {
            if (subscription.matches(run.getRunId())) {
                publishToSubscription(subscription, run);
            }
        }
    }

    private void publishToSubscription(RunSubscription subscription, RunRecord run) {
        for (RunEventRecord event : run.getEvents()) {
            if (subscription.markSent(event.getEventId())) {
                try {
                    subscription.getEmitter().send(
                        SseEmitter.event()
                            .id(event.getEventId())
                            .name(event.getEventType())
                            .data(event)
                    );
                } catch (IOException exc) {
                    subscriptions.remove(subscription);
                    return;
                }
            }
        }
    }

    private static class RunSubscription {
        private final String runId;
        private final SseEmitter emitter;
        private final Set<String> sentEventIds = new HashSet<String>();

        RunSubscription(String runId, SseEmitter emitter) {
            this.runId = runId;
            this.emitter = emitter;
        }

        boolean matches(String candidateRunId) {
            return runId.equals(candidateRunId);
        }

        SseEmitter getEmitter() {
            return emitter;
        }

        boolean markSent(String eventId) {
            return sentEventIds.add(eventId);
        }
    }
}
