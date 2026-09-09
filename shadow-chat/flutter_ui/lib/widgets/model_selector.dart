import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';

/// Dropdown zur Modellauswahl (unten rechts).
///
/// Kommuniziert mit der Shadow LLM Engine über den shadow-server.
/// Standardmodell: „Shadow Model".
class ModelSelector extends StatelessWidget {
  const ModelSelector({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final theme = Theme.of(context);
    final models = state.models;

    if (models.isEmpty) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: theme.colorScheme.surface,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: theme.dividerColor),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.smart_toy, size: 16, color: state.highlight),
            const SizedBox(width: 6),
            const Text('Keine Modelle'),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: theme.dividerColor),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: state.selectedModelId,
          icon: const Icon(Icons.expand_more),
          style: theme.textTheme.bodyMedium,
          items: models
              .map((m) => DropdownMenuItem(
                    value: m.modelId,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.smart_toy, size: 16, color: state.highlight),
                        const SizedBox(width: 6),
                        Text(m.displayName),
                      ],
                    ),
                  ))
              .toList(),
          onChanged: (v) {
            if (v != null) state.selectModel(v);
          },
        ),
      ),
    );
  }
}
