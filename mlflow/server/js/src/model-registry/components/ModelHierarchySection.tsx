import React, { useCallback, useEffect, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';
import { Button, Input, Modal, Typography, useDesignSystemTheme } from '@databricks/design-system';
import { Link } from '../../common/utils/RoutingUtils';
import Utils from '../../common/utils/Utils';
import { CollapsibleSection } from '../../common/components/CollapsibleSection';
import { ModelRegistryRoutes } from '../routes';
import { Services } from '../services';

/**
 * Quote a value for a registered model search filter, choosing a quote character that the
 * value does not contain (mirrors `_quote_filter_value` in the Python client).
 */
export const quoteFilterValue = (value: string) => {
  if (value.includes("'") && !value.includes('"')) {
    return `"${value}"`;
  }
  return `'${value.replace(/'/g, "\\'")}'`;
};

type ModelHierarchySectionProps = {
  modelName: string;
  parentName?: string | null;
  /** Called after the parent was changed so the page can re-fetch the model. */
  onParentChanged: () => void;
};

export const ModelHierarchySection = ({ modelName, parentName, onParentChanged }: ModelHierarchySectionProps) => {
  const intl = useIntl();
  const { theme } = useDesignSystemTheme();
  const [subModels, setSubModels] = useState<string[]>([]);
  const [loadingSubModels, setLoadingSubModels] = useState(false);
  const [subModelsLoaded, setSubModelsLoaded] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [parentInput, setParentInput] = useState(parentName || '');
  const [saving, setSaving] = useState(false);

  const fetchSubModels = useCallback(async () => {
    setLoadingSubModels(true);
    try {
      const names: string[] = [];
      let pageToken: string | undefined = undefined;
      do {
        const response: any = await Services.searchRegisteredModels({
          filter: `parent_name = ${quoteFilterValue(modelName)}`,
          max_results: 1000,
          order_by: ['name ASC'],
          ...(pageToken ? { page_token: pageToken } : {}),
        });
        (response?.registered_models || []).forEach((m: any) => names.push(m.name));
        pageToken = response?.next_page_token;
      } while (pageToken);
      setSubModels(names);
    } catch (e) {
      Utils.logErrorAndNotifyUser(e);
    } finally {
      setLoadingSubModels(false);
      setSubModelsLoaded(true);
    }
  }, [modelName]);

  useEffect(() => {
    fetchSubModels();
  }, [fetchSubModels]);

  const openModal = () => {
    setParentInput(parentName || '');
    setModalVisible(true);
  };

  const saveParent = async () => {
    setSaving(true);
    try {
      const trimmed = parentInput.trim();
      await Services.setRegisteredModelParent({
        name: modelName,
        ...(trimmed ? { parent_name: trimmed } : {}),
      });
      setModalVisible(false);
      onParentChanged();
    } catch (e) {
      Utils.logErrorAndNotifyUser(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <CollapsibleSection
      // Re-mount once sub-models are loaded so the default open/closed state reflects them.
      key={subModelsLoaded ? 'loaded' : 'loading'}
      title={
        <FormattedMessage
          defaultMessage="Model hierarchy"
          description="Title text for the parent / sub-model section on the model view page"
        />
      }
      defaultCollapsed={!parentName && subModels.length === 0}
      data-test-id="model-hierarchy-section"
    >
      <div css={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.sm }}>
        <div css={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
          <Typography.Text bold>
            <FormattedMessage
              defaultMessage="Parent model:"
              description="Label for the parent registered model on the model view page"
            />
          </Typography.Text>
          {parentName ? (
            <Link to={ModelRegistryRoutes.getModelPageRoute(parentName)} data-testid="model-hierarchy-parent-link">
              {parentName}
            </Link>
          ) : (
            <Typography.Text color="secondary">
              <FormattedMessage
                defaultMessage="None (top-level model)"
                description="Shown when a registered model has no parent model"
              />
            </Typography.Text>
          )}
          <Button
            componentId="mlflow.model_registry.model_hierarchy.change_parent"
            size="small"
            onClick={openModal}
            data-testid="model-hierarchy-change-parent"
          >
            <FormattedMessage
              defaultMessage="Change parent"
              description="Button to change the parent registered model on the model view page"
            />
          </Button>
        </div>
        <div>
          <Typography.Text bold>
            <FormattedMessage
              defaultMessage="Sub-models ({count})"
              description="Label for the list of sub-models of a registered model"
              values={{ count: subModels.length }}
            />
          </Typography.Text>
          {loadingSubModels ? null : subModels.length === 0 ? (
            <div>
              <Typography.Text color="secondary">
                <FormattedMessage
                  defaultMessage="No sub-models. Create a model with this model as its parent, or set the parent of an existing model."
                  description="Empty state for the sub-models list on the model view page"
                />
              </Typography.Text>
            </div>
          ) : (
            <ul css={{ margin: `${theme.spacing.xs}px 0 0 0`, paddingLeft: theme.spacing.lg }}>
              {subModels.map((name) => (
                <li key={name}>
                  <Link to={ModelRegistryRoutes.getModelPageRoute(name)} data-testid="model-hierarchy-sub-model-link">
                    {name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <Modal
        componentId="mlflow.model_registry.model_hierarchy.change_parent_modal"
        title={intl.formatMessage({
          defaultMessage: 'Change parent model',
          description: 'Title of the modal to change the parent registered model',
        })}
        visible={modalVisible}
        confirmLoading={saving}
        onOk={saveParent}
        onCancel={() => setModalVisible(false)}
        okText={intl.formatMessage({
          defaultMessage: 'Save',
          description: 'Save button in the change parent model modal',
        })}
        cancelText={intl.formatMessage({
          defaultMessage: 'Cancel',
          description: 'Cancel button in the change parent model modal',
        })}
      >
        <Typography.Paragraph>
          <FormattedMessage
            defaultMessage="Enter the name of an existing registered model to group {name} under. Leave empty to make it a top-level model."
            description="Help text in the change parent model modal"
            values={{ name: <code>{modelName}</code> }}
          />
        </Typography.Paragraph>
        <Input
          componentId="mlflow.model_registry.model_hierarchy.parent_input"
          value={parentInput}
          placeholder={intl.formatMessage({
            defaultMessage: 'Parent model name',
            description: 'Placeholder for the parent model name input',
          })}
          onChange={(e) => setParentInput(e.target.value)}
          onPressEnter={saveParent}
          data-testid="model-hierarchy-parent-input"
        />
      </Modal>
    </CollapsibleSection>
  );
};
