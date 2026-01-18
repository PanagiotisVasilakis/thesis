import { Circle, Popup } from 'react-leaflet';

export default function CellMarker({ cell }) {
    return (
        <Circle
            center={[cell.latitude, cell.longitude]}
            radius={cell.radius}
            pathOptions={{
                color: '#3b82f6',
                fillColor: '#3b82f6',
                fillOpacity: 0.1,
                weight: 2,
            }}
        >
            <Popup>
                <div className="text-sm">
                    <strong>{cell.name}</strong>
                    <br />
                    ID: {cell.cell_id}
                    <br />
                    Radius: {cell.radius}m
                    <br />
                    {cell.description}
                </div>
            </Popup>
        </Circle>
    );
}
