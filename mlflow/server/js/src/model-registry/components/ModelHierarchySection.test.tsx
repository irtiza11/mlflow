import { renderWithIntl, act, screen, waitFor } from '../../common/utils/TestUtils.react18';
import userEvent from '@testing-library/user-event-14';
import { MemoryRouter } from '../../common/utils/RoutingUtils';
import { DesignSystemProvider } from '@databricks/design-system';
import { ModelHierarchySection, quoteFilterValue } from './ModelHierarchySection';
import { Services } from '../services';

jest.mock('../services', () => ({
  Services: {
    searchRegisteredModels: jest.fn(),
    setRegisteredModelParent: jest.fn(),
  },
}));

const renderSection = (props: Partial<React.ComponentProps<typeof ModelHierarchySection>> = {}) => {
  const onParentChanged = jest.fn();
  renderWithIntl(
    <MemoryRouter>
      <DesignSystemProvider>
        <ModelHierarchySection modelName="fraud" onParentChanged={onParentChanged} {...props} />
      </DesignSystemProvider>
    </MemoryRouter>,
  );
  return { onParentChanged };
};

describe('ModelHierarchySection', () => {
  beforeEach(() => {
    jest.mocked(Services.searchRegisteredModels).mockReset();
    jest.mocked(Services.setRegisteredModelParent).mockReset();
  });

  test('quoteFilterValue picks a safe quote character', () => {
    expect(quoteFilterValue('abc')).toEqual("'abc'");
    expect(quoteFilterValue("o'brien")).toEqual('"o\'brien"');
  });

  test('expands automatically when the model has sub-models but no parent', async () => {
    jest.mocked(Services.searchRegisteredModels).mockResolvedValue({
      registered_models: [{ name: 'fraud-card' }],
    } as any);
    renderSection();
    await waitFor(() => expect(screen.getByTestId('model-hierarchy-sub-model-link')).toHaveTextContent('fraud-card'));
  });

  test('lists sub-models and parent link', async () => {
    jest.mocked(Services.searchRegisteredModels).mockResolvedValue({
      registered_models: [{ name: 'fraud-card' }, { name: 'fraud-wire' }],
    } as any);
    renderSection({ parentName: 'risk' });

    expect(Services.searchRegisteredModels).toHaveBeenCalledWith(
      expect.objectContaining({ filter: "parent_name = 'fraud'" }),
    );
    await waitFor(() => expect(screen.getAllByTestId('model-hierarchy-sub-model-link')).toHaveLength(2));
    expect(screen.getByText('Sub-models (2)')).toBeInTheDocument();
    expect(screen.getByTestId('model-hierarchy-parent-link')).toHaveTextContent('risk');
  });

  test('shows top-level state and changes parent', async () => {
    jest.mocked(Services.searchRegisteredModels).mockResolvedValue({ registered_models: [] } as any);
    jest.mocked(Services.setRegisteredModelParent).mockResolvedValue({} as any);
    const { onParentChanged } = renderSection();

    // Flat models start with the section collapsed; expand it.
    await waitFor(() => expect(Services.searchRegisteredModels).toHaveBeenCalled());
    // Let the sub-model fetch settle (the section re-mounts once loaded).
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await userEvent.click(screen.getByRole('button', { name: /Model hierarchy/ }));
    await waitFor(() => expect(screen.getByText('None (top-level model)')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('model-hierarchy-change-parent'));
    await userEvent.type(screen.getByTestId('model-hierarchy-parent-input'), 'risk');
    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    });

    expect(Services.setRegisteredModelParent).toHaveBeenCalledWith({ name: 'fraud', parent_name: 'risk' });
    expect(onParentChanged).toHaveBeenCalled();
  });
});
