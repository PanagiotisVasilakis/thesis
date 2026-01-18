import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';

// Custom UE icon
const ueIcon = new L.Icon({
    iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
});

export default function UEMarker({ ue, onClick }) {
    return (
        <Marker
            position={[ue.latitude, ue.longitude]}
            icon={ueIcon}
            eventHandlers={{
                click: () => onClick?.(ue),
            }}
        >
            <Popup>
                <div className="text-sm">
                    <strong>{ue.name}</strong>
                    <br />
                    SUPI: {ue.supi}
                    <br />
                    Cell: {ue.cell_id_hex || 'None'}
                    <br />
                    Speed: {ue.speed}
                </div>
            </Popup>
        </Marker>
    );
}
